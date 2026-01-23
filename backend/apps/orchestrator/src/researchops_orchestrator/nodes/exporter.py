"""
Exporter node - assembles and persists final report artifacts.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.artifacts import ArtifactRow
from db.models.draft_sections import DraftSectionRow
from db.models.run_sections import RunSectionRow
from db.models.runs import RunRow, RunStatusDb
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import OrchestratorState


_CITATION_PATTERN = re.compile(r"\[CITE:([a-f0-9-]+)\]")


@instrument_node("export")
def exporter_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Assemble final report artifacts from run_sections + draft_sections.
    """
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="export.started",
        stage="export",
        data={"run_id": str(state.run_id)},
    )

    run_row = session.execute(
        select(RunRow).where(RunRow.tenant_id == state.tenant_id, RunRow.id == state.run_id)
    ).scalar_one_or_none()
    if run_row is None:
        raise ValueError("Run not found for export.")

    sections = _load_run_sections(session, tenant_id=state.tenant_id, run_id=state.run_id)
    drafts = _load_draft_sections(session, tenant_id=state.tenant_id, run_id=state.run_id)

    markdown, warnings = _assemble_report(
        state=state,
        sections=sections,
        drafts=drafts,
    )
    markdown = _apply_citation_footnotes(
        markdown,
        evidence_snippets=state.evidence_snippets,
        vetted_sources=state.vetted_sources,
    )

    artifact_types: list[str] = []
    _upsert_artifact(
        session,
        tenant_id=state.tenant_id,
        project_id=run_row.project_id,
        run_id=state.run_id,
        artifact_type="report_md",
        blob_ref=f"inline://runs/{state.run_id}/report.md",
        mime_type="text/markdown",
        content=markdown.encode("utf-8"),
        metadata_json={
            "filename": "report.md",
            "markdown": markdown,
        },
    )
    artifact_types.append("report_md")

    pdf_bytes, pdf_warning = _maybe_render_pdf(markdown)
    if pdf_warning:
        warnings.append(pdf_warning)
    if pdf_bytes:
        _upsert_artifact(
            session,
            tenant_id=state.tenant_id,
            project_id=run_row.project_id,
            run_id=state.run_id,
            artifact_type="report_pdf",
            blob_ref=f"inline://runs/{state.run_id}/report.pdf",
            mime_type="application/pdf",
            content=pdf_bytes,
            metadata_json={
                "filename": "report.pdf",
                "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            },
        )
        artifact_types.append("report_pdf")

    now = datetime.now(UTC)
    run_row.current_stage = "export"
    run_row.finished_at = now
    run_row.updated_at = now
    run_row.status = RunStatusDb.succeeded
    if warnings:
        usage = dict(run_row.usage_json or {})
        usage["warnings"] = warnings
        run_row.usage_json = usage

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="export.completed",
        stage="export",
        data={"artifact_types": artifact_types},
    )
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="run.succeeded_with_warnings" if warnings else "run.succeeded",
        stage="export",
        data={"warnings": warnings},
    )

    state.artifacts = {"report.md": markdown}
    if pdf_bytes:
        state.artifacts["report.pdf"] = pdf_bytes

    return state


def _load_run_sections(
    session: Session,
    *,
    tenant_id,
    run_id,
) -> list[RunSectionRow]:
    return (
        session.execute(
            select(RunSectionRow)
            .where(RunSectionRow.tenant_id == tenant_id, RunSectionRow.run_id == run_id)
            .order_by(RunSectionRow.section_order.asc())
        )
        .scalars()
        .all()
    )


def _load_draft_sections(
    session: Session,
    *,
    tenant_id,
    run_id,
) -> dict[str, DraftSectionRow]:
    rows = (
        session.execute(
            select(DraftSectionRow).where(
                DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id
            )
        )
        .scalars()
        .all()
    )
    return {row.section_id: row for row in rows}


def _assemble_report(
    *,
    state: OrchestratorState,
    sections: list[RunSectionRow],
    drafts: dict[str, DraftSectionRow],
) -> tuple[str, list[str]]:
    warnings: list[str] = []

    if sections and drafts:
        lines: list[str] = [f"# Research Report: {state.user_query}", ""]
        for section in sections:
            lines.append(f"## {section.section_order}. {section.title}")
            lines.append("")
            draft = drafts.get(section.section_id)
            if not draft or not draft.text.strip():
                warnings.append(f"Missing draft for section_id={section.section_id}.")
                lines.append("_Draft missing for this section._")
            else:
                lines.append(draft.text.strip())
            lines.append("")
        return "\n".join(lines).strip() + "\n", warnings

    if not sections:
        warnings.append("run_sections missing; assembled from state.draft_text.")
    if not drafts:
        warnings.append("draft_sections missing; assembled from state.draft_text.")
    if state.draft_text:
        return state.draft_text.strip() + "\n", warnings

    raise ValueError("No draft content available for export.")


def _apply_citation_footnotes(
    markdown: str,
    *,
    evidence_snippets: list,
    vetted_sources: list,
) -> str:
    if not markdown:
        return markdown

    citation_map = {}
    for snippet in evidence_snippets or []:
        source = next((s for s in vetted_sources or [] if s.source_id == snippet.source_id), None)
        if source:
            citation_map[str(snippet.snippet_id)] = source

    citation_counter = 0
    citation_ids_used: dict[str, int] = {}
    footnotes: list[str] = []

    def replace_citation(match: re.Match) -> str:
        nonlocal citation_counter
        snippet_id = match.group(1)
        source = citation_map.get(snippet_id)
        if source is None:
            return match.group(0)

        if snippet_id in citation_ids_used:
            footnote_num = citation_ids_used[snippet_id]
        else:
            citation_counter += 1
            footnote_num = citation_counter
            citation_ids_used[snippet_id] = footnote_num

            authors_str = ", ".join(source.authors[:3]) if source.authors else "Unknown"
            if source.authors and len(source.authors) > 3:
                authors_str += " et al."

            footnote = f"[^{footnote_num}]: {authors_str}. {source.title}. {source.year or 'n.d.'}."
            if source.url:
                footnote += f" [{source.url}]({source.url})"
            footnotes.append(footnote)

        return f"[^{footnote_num}]"

    final_text = _CITATION_PATTERN.sub(replace_citation, markdown)
    if footnotes:
        final_text += "\n\n---\n\n## References\n\n"
        final_text += "\n\n".join(footnotes)

    return final_text


def _upsert_artifact(
    session: Session,
    *,
    tenant_id,
    project_id,
    run_id,
    artifact_type: str,
    blob_ref: str,
    mime_type: str,
    content: bytes,
    metadata_json: dict,
) -> None:
    row = (
        session.execute(
            select(ArtifactRow).where(
                ArtifactRow.tenant_id == tenant_id,
                ArtifactRow.run_id == run_id,
                ArtifactRow.artifact_type == artifact_type,
            )
        )
        .scalars()
        .one_or_none()
    )
    size_bytes = len(content)
    if row:
        row.blob_ref = blob_ref
        row.mime_type = mime_type
        row.size_bytes = size_bytes
        row.metadata_json = metadata_json
        session.flush()
        return

    session.add(
        ArtifactRow(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            artifact_type=artifact_type,
            blob_ref=blob_ref,
            mime_type=mime_type,
            size_bytes=size_bytes,
            metadata_json=metadata_json,
        )
    )
    session.flush()


def _maybe_render_pdf(markdown: str) -> tuple[bytes | None, str | None]:
    raw = os.getenv("EXPORT_REPORT_PDF", "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return None, None

    try:
        import markdown as md
    except Exception:
        return None, "PDF export requested but markdown package is not installed."

    try:
        from weasyprint import HTML
    except Exception:
        return None, "PDF export requested but weasyprint is not installed."

    try:
        html = md.markdown(markdown, extensions=["extra"])
        pdf_bytes = HTML(string=html).write_pdf()
        return pdf_bytes, None
    except Exception as exc:
        return None, f"PDF export failed: {exc}"


