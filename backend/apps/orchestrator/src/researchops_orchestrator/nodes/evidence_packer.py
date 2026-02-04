"""
Evidence pack node - builds section-level evidence packs.

Selects semantically relevant snippets per section and stores membership
in section_evidence to gate what the writer can cite.
"""

from __future__ import annotations

import hashlib
import os
from typing import Iterable, Protocol

from sqlalchemy.orm import Session

from db.models.section_evidence import SectionEvidenceRow
from db.models.snippet_embeddings import SnippetEmbeddingRow
from db.models.snippets import SnippetRow
from db.models.snapshots import SnapshotRow
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import EvidenceSnippetRef, OrchestratorState, OutlineSection
from researchops_retrieval.search import search_snippets
from researchops_orchestrator.embeddings import (
    get_hf_client,
    get_ollama_client,
    get_sentence_transformer_client,
)


class EmbeddingClient(Protocol):
    model_name: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...



def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def _env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def _resolve_embed_model() -> str:
    for name in ("EVIDENCE_EMBED_MODEL", "OLLAMA_EMBED_MODEL", "EMBEDDING_MODEL", "RETRIEVER_EMBED_MODEL"):
        raw = os.getenv(name)
        if raw and raw.strip():
            return raw.strip()
    return "BAAI/bge-m3"


def _resolve_embed_provider() -> str:
    raw = os.getenv("EVIDENCE_EMBED_PROVIDER") or os.getenv("RETRIEVER_EMBED_PROVIDER")
    if raw and raw.strip():
        return raw.strip().lower()
    return "local"


def _resolve_embed_device() -> str:
    raw = os.getenv("EVIDENCE_EMBED_DEVICE") or os.getenv("EMBEDDING_DEVICE")
    if raw and raw.strip():
        return raw.strip()
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_embed_dtype(device: str) -> str | None:
    raw = os.getenv("EVIDENCE_EMBED_DTYPE")
    if raw and raw.strip():
        return raw.strip().lower()
    if device.startswith("cuda"):
        return "float16"
    return None


def _resolve_embed_normalize() -> bool:
    raw = os.getenv("EVIDENCE_EMBED_NORMALIZE")
    if not raw:
        return True
    return raw.strip().lower() not in {"0", "false", "no"}


def _resolve_embed_trust_remote_code(model_name: str) -> bool:
    raw = os.getenv("EVIDENCE_EMBED_TRUST_REMOTE_CODE")
    if raw and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes"}
    return "bge-m3" in model_name.lower()


def _resolve_embed_max_seq_len() -> int | None:
    raw = os.getenv("EVIDENCE_EMBED_MAX_SEQ_LEN") or os.getenv("RETRIEVER_EMBED_MAX_SEQ_LEN")
    if not raw or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _get_embed_client() -> EmbeddingClient:
    provider = _resolve_embed_provider()
    if provider == "ollama":
        model_name = _resolve_embed_model()
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        timeout_seconds = _env_int("OLLAMA_TIMEOUT_SECONDS", 60, min_value=5)
        return get_ollama_client(
            model_name=model_name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    if provider in {"hf", "huggingface", "hosted", "inference"}:
        model_name = os.getenv("HF_EMBED_MODEL", "BAAI/bge-m3").strip()
        base_url = os.getenv(
            "HF_INFERENCE_BASE_URL",
            "https://router.huggingface.co/hf-inference/models",
        ).strip()
        api_key = os.getenv("HF_TOKEN", "").strip()
        if not api_key:
            raise ValueError("HF_TOKEN is required for hosted embeddings.")
        timeout_seconds = _env_int("HF_TIMEOUT_SECONDS", 60, min_value=5)
        wait_for_model = os.getenv("HF_WAIT_FOR_MODEL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        return get_hf_client(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            wait_for_model=wait_for_model,
        )

    model_name = _resolve_embed_model()
    device = _resolve_embed_device()
    dtype = _resolve_embed_dtype(device)
    normalize = _resolve_embed_normalize()
    trust_remote_code = _resolve_embed_trust_remote_code(model_name)
    max_seq_length = _resolve_embed_max_seq_len()
    return get_sentence_transformer_client(
        model_name=model_name,
        device=device,
        normalize_embeddings=normalize,
        max_seq_length=max_seq_length,
        dtype=dtype,
        trust_remote_code=trust_remote_code,
    )


def _embed_texts_batched(
    client: EmbeddingClient, texts: list[str], *, batch_size: int
) -> list[list[float]]:
    if not texts:
        return []
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(client.embed_texts(batch))
    return embeddings


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section_query_text(section: OutlineSection) -> str:
    parts = [
        section.title,
        section.goal,
        " ".join(section.key_points),
        " ".join(section.suggested_evidence_themes),
    ]
    return " ".join(part for part in parts if part).strip()


def _dedupe_results(results: Iterable[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for result in results:
        snippet_id = str(result["snippet_id"])
        if snippet_id not in seen or result["similarity"] > seen[snippet_id]["similarity"]:
            seen[snippet_id] = result
    return list(seen.values())


def _select_diverse_snippets(
    results: list[dict],
    *,
    max_count: int,
    per_source_cap: int,
) -> list[dict]:
    selected: list[dict] = []
    source_counts: dict[str, int] = {}

    for result in results:
        if len(selected) >= max_count:
            break
        source_id = str(result["source_id"])
        if source_counts.get(source_id, 0) >= per_source_cap:
            continue
        selected.append(result)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1

    if len(selected) < max_count:
        for result in results:
            if len(selected) >= max_count:
                break
            if result in selected:
                continue
            selected.append(result)

    return selected


def _ensure_snippets_from_abstracts(
    session: Session,
    *,
    tenant_id,
    vetted_sources: list,
    embed_client: SentenceTransformerEmbedClient,
    embedding_model: str,
) -> None:
    if not vetted_sources:
        return

    source_ids = [source.source_id for source in vetted_sources]
    exists_any = (
        session.query(SnippetRow.id)
        .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
        .filter(SnippetRow.tenant_id == tenant_id, SnapshotRow.source_id.in_(source_ids))
        .first()
    )
    if exists_any:
        return

    new_snippets: list[tuple[SnippetRow, str]] = []
    for source in vetted_sources:
        text = (source.abstract or source.title or "").strip()
        if not text:
            continue
        snapshot_version = _next_snapshot_version(session, tenant_id, source.source_id)
        snapshot = SnapshotRow(
            tenant_id=tenant_id,
            source_id=source.source_id,
            snapshot_version=snapshot_version,
            content_type="text/plain",
            blob_ref=f"abstract:{source.canonical_id}",
            sha256=_sha256_hex(text),
            size_bytes=len(text),
            metadata_json={"origin": "abstract_fallback"},
        )
        session.add(snapshot)
        session.flush()

        snippet = SnippetRow(
            tenant_id=tenant_id,
            snapshot_id=snapshot.id,
            snippet_index=0,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=None,
            sha256=_sha256_hex(text),
            risk_flags_json={},
        )
        session.add(snippet)
        session.flush()
        new_snippets.append((snippet, text))

    if not new_snippets:
        return

    batch_size = _env_int("EVIDENCE_EMBED_BATCH", 16, min_value=1)
    vectors = _embed_texts_batched(embed_client, [text for _, text in new_snippets], batch_size=batch_size)
    if len(vectors) != len(new_snippets):
        raise ValueError("Mismatch between snippets and embeddings for abstract fallback.")

    for (snippet, _), vector in zip(new_snippets, vectors):
        session.add(
            SnippetEmbeddingRow(
                tenant_id=tenant_id,
                snippet_id=snippet.id,
                embedding_model=embedding_model,
                dims=len(vector),
                embedding=vector,
            )
        )
    session.flush()


def _next_snapshot_version(session: Session, tenant_id, source_id) -> int:
    latest = (
        session.query(SnapshotRow.snapshot_version)
        .filter(SnapshotRow.tenant_id == tenant_id, SnapshotRow.source_id == source_id)
        .order_by(SnapshotRow.snapshot_version.desc())
        .first()
    )
    return (latest[0] + 1) if latest else 1


def _persist_section_evidence(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    snippet_ids: list,
) -> None:
    session.query(SectionEvidenceRow).filter(
        SectionEvidenceRow.tenant_id == tenant_id,
        SectionEvidenceRow.run_id == run_id,
        SectionEvidenceRow.section_id == section_id,
    ).delete()

    rows = [
        SectionEvidenceRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            snippet_id=snippet_id,
        )
        for snippet_id in snippet_ids
    ]
    if rows:
        session.bulk_save_objects(rows)
    session.flush()


@instrument_node("evidence_pack")
def evidence_pack_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required before building evidence packs.")

    embed_client = _get_embed_client()
    embedding_model = embed_client.model_name

    _ensure_snippets_from_abstracts(
        session,
        tenant_id=state.tenant_id,
        vetted_sources=state.vetted_sources,
        embed_client=embed_client,
        embedding_model=embedding_model,
    )

    source_ids = [source.source_id for source in state.vetted_sources]
    search_limit = _env_int("EVIDENCE_SEARCH_LIMIT", 60, min_value=10)
    min_similarity = _env_float("EVIDENCE_MIN_SIMILARITY", 0.35, min_value=0.0)
    min_required = _env_int("EVIDENCE_MIN_REQUIRED", 5, min_value=1)
    min_snippets = _env_int("EVIDENCE_SNIPPET_MIN", 8, min_value=1)
    max_snippets = _env_int("EVIDENCE_SNIPPET_MAX", 20, min_value=min_snippets)
    per_source_cap = _env_int("EVIDENCE_PER_SOURCE_CAP", 3, min_value=1)
    embed_batch_size = _env_int("EVIDENCE_EMBED_BATCH", 16, min_value=1)

    evidence_refs: dict[str, EvidenceSnippetRef] = {}
    section_snippet_refs: dict[str, list[EvidenceSnippetRef]] = {}

    section_queries: list[tuple[OutlineSection, str]] = []
    for section in outline.sections:
        query_text = _section_query_text(section)
        if query_text:
            section_queries.append((section, query_text))

    query_vectors = _embed_texts_batched(
        embed_client,
        [query for _, query in section_queries],
        batch_size=embed_batch_size,
    )
    if len(query_vectors) != len(section_queries):
        raise ValueError("Mismatch between outline sections and query embeddings.")

    for (section, _), query_embedding in zip(section_queries, query_vectors):
        results = search_snippets(
            session=session,
            tenant_id=state.tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            limit=search_limit,
            min_similarity=min_similarity,
            source_ids=source_ids or None,
        )

        if len(results) < min_required:
            relaxed = search_snippets(
                session=session,
                tenant_id=state.tenant_id,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                limit=search_limit + 30,
                min_similarity=max(0.0, min_similarity - 0.15),
                source_ids=source_ids or None,
            )
            results = _dedupe_results(list(results) + list(relaxed))

        results = sorted(results, key=lambda item: item["similarity"], reverse=True)
        selected = _select_diverse_snippets(
            results,
            max_count=max_snippets,
            per_source_cap=per_source_cap,
        )

        if len(selected) < min_snippets and len(results) > len(selected):
            selected = _select_diverse_snippets(
                results,
                max_count=min_snippets,
                per_source_cap=max(per_source_cap, min_snippets),
            )

        snippet_ids = [item["snippet_id"] for item in selected]
        _persist_section_evidence(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            snippet_ids=snippet_ids,
        )

        section_refs: list[EvidenceSnippetRef] = []
        for item in selected:
            snippet_id = str(item["snippet_id"])
            ref = evidence_refs.get(snippet_id)
            if ref is None:
                snippet_text = item["snippet_text"] or ""
                char_start = item["char_start"] if item["char_start"] is not None else 0
                char_end = item["char_end"] if item["char_end"] is not None else len(snippet_text)
                ref = EvidenceSnippetRef(
                    snippet_id=item["snippet_id"],
                    source_id=item["source_id"],
                    text=snippet_text,
                    char_start=char_start,
                    char_end=char_end,
                )
                evidence_refs[snippet_id] = ref
            section_refs.append(ref)
        section_snippet_refs[section.section_id] = section_refs

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evidence_pack.created",
            stage="evidence_pack",
            data={
                "section_id": section.section_id,
                "snippet_count": len(snippet_ids),
            },
        )

    state.evidence_snippets = list(evidence_refs.values())
    state.section_evidence_snippets = section_snippet_refs
    return state
