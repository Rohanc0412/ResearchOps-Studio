"""CRUD operations for section_claims."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from db.models.section_claims import SectionClaimRow


def upsert_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
    claims: list[str],
) -> None:
    """Replace all stored claims for a section with the new list."""
    delete_section_claims(session, tenant_id=tenant_id, run_id=run_id, section_id=section_id)
    for idx, text in enumerate(claims):
        session.add(SectionClaimRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            claim_index=idx,
            claim_text=text,
        ))


def load_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
) -> list[str]:
    """Return ordered list of claim strings for a section, empty if none cached."""
    rows = (
        session.query(SectionClaimRow)
        .filter(
            SectionClaimRow.tenant_id == tenant_id,
            SectionClaimRow.run_id == run_id,
            SectionClaimRow.section_id == section_id,
        )
        .order_by(SectionClaimRow.claim_index)
        .all()
    )
    return [r.claim_text for r in rows]


def delete_section_claims(
    session: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    section_id: str,
) -> None:
    """Delete all cached claims for a section."""
    session.query(SectionClaimRow).filter(
        SectionClaimRow.tenant_id == tenant_id,
        SectionClaimRow.run_id == run_id,
        SectionClaimRow.section_id == section_id,
    ).delete(synchronize_session=False)
