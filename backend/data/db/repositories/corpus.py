from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.source_authors import SourceAuthorRow
from db.models.source_identifiers import SourceIdentifierRow
from db.models.sources import SourceRow


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _normalize_author_names(authors: list[str] | None) -> list[str]:
    return [str(value).strip() for value in authors or [] if str(value).strip()]


def list_source_author_names(source: SourceRow) -> list[str]:
    rows = sorted(source.authors, key=lambda row: row.author_order)
    return [row.author_name for row in rows]


def replace_source_authors(source: SourceRow, authors: list[str] | None) -> None:
    normalized = _normalize_author_names(authors)
    existing = sorted(source.authors, key=lambda row: row.author_order)

    for index, value in enumerate(normalized):
        if index < len(existing):
            row = existing[index]
            row.author_order = index
            row.author_name = value
            continue

        source.authors.append(
            SourceAuthorRow(
                tenant_id=source.tenant_id,
                author_order=index,
                author_name=value,
            )
        )

    for row in existing[len(normalized) :]:
        source.authors.remove(row)


def get_source_identifier(source: SourceRow, identifier_type: str) -> str | None:
    for row in source.identifiers:
        if row.identifier_type == identifier_type:
            return row.identifier_value
    return None


def set_source_identifier(
    source: SourceRow,
    identifier_type: str,
    identifier_value: str | None,
) -> None:
    rows = [row for row in source.identifiers if row.identifier_type != identifier_type]
    if identifier_value:
        rows.append(
            SourceIdentifierRow(
                tenant_id=source.tenant_id,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                is_primary=identifier_type == "canonical_id",
            )
        )
    source.identifiers = rows


async def get_source(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> SourceRow | None:
    stmt = (
        select(SourceRow)
        .where(SourceRow.tenant_id == tenant_id, SourceRow.id == source_id)
        .options(selectinload(SourceRow.authors), selectinload(SourceRow.identifiers))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_source_by_canonical_id(
    session: AsyncSession, *, tenant_id: UUID, canonical_id: str
) -> SourceRow | None:
    stmt = (
        select(SourceRow)
        .where(SourceRow.tenant_id == tenant_id, SourceRow.canonical_id == canonical_id)
        .options(selectinload(SourceRow.authors), selectinload(SourceRow.identifiers))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_or_get_source(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    canonical_id: str,
    source_type: str,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    origin: str | None = None,
    cited_by_count: int | None = None,
    url: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    metadata: dict | None = None,
) -> SourceRow:
    existing = await get_source_by_canonical_id(session, tenant_id=tenant_id, canonical_id=canonical_id)
    now = _now_utc()
    metadata_json = dict(metadata or {})

    if existing:
        updated = False
        if title and existing.title != title:
            existing.title = title
            updated = True
        normalized_authors = _normalize_author_names(authors)
        current_authors = list_source_author_names(existing)
        if normalized_authors and current_authors != normalized_authors:
            replace_source_authors(existing, normalized_authors)
            updated = True
        if year and existing.year != year:
            existing.year = year
            updated = True
        if venue and existing.venue != venue:
            existing.venue = venue
            updated = True
        if origin and existing.origin != origin:
            existing.origin = origin
            updated = True
        if cited_by_count is not None and (
            existing.cited_by_count is None or cited_by_count > existing.cited_by_count
        ):
            existing.cited_by_count = cited_by_count
            updated = True
        if url and existing.url != url:
            existing.url = url
            updated = True
        if doi and get_source_identifier(existing, "doi") != doi:
            set_source_identifier(existing, "doi", doi)
            updated = True
        if arxiv_id and get_source_identifier(existing, "arxiv_id") != arxiv_id:
            set_source_identifier(existing, "arxiv_id", arxiv_id)
            updated = True
        if metadata_json:
            merged = dict(existing.metadata_json or {})
            for key, value in metadata_json.items():
                if value is None:
                    continue
                if key not in merged or merged[key] in (None, "", [], {}):
                    merged[key] = value
            if merged != existing.metadata_json:
                existing.metadata_json = merged
                updated = True
        if updated:
            existing.updated_at = now
            await session.flush()
        return existing

    source = SourceRow(
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        source_type=source_type,
        title=title,
        year=year,
        venue=venue,
        origin=origin,
        cited_by_count=cited_by_count,
        url=url,
        metadata_json=metadata_json,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(source)
        await session.flush()
    except IntegrityError:
        # Another worker inserted the same canonical_id concurrently.
        # Roll back to the savepoint and return the row they inserted.
        await session.rollback()
        race_winner = await get_source_by_canonical_id(session, tenant_id=tenant_id, canonical_id=canonical_id)
        if race_winner is None:
            raise  # genuine integrity error unrelated to this insert
        return race_winner
    replace_source_authors(source, authors)
    set_source_identifier(source, "doi", doi)
    set_source_identifier(source, "arxiv_id", arxiv_id)
    await session.flush()
    return source


# ---------------------------------------------------------------------------
# Sync variant for orchestrator nodes (receive a sync sqlalchemy.orm.Session)
# ---------------------------------------------------------------------------

def _get_source_by_canonical_id_sync(
    session: "Session",
    *,
    tenant_id: UUID,
    canonical_id: str,
) -> SourceRow | None:
    from sqlalchemy import select
    stmt = (
        select(SourceRow)
        .where(SourceRow.tenant_id == tenant_id, SourceRow.canonical_id == canonical_id)
        .options(selectinload(SourceRow.authors), selectinload(SourceRow.identifiers))
    )
    return session.execute(stmt).scalar_one_or_none()


def create_or_get_source_sync(
    *,
    session: "Session",
    tenant_id: UUID,
    canonical_id: str,
    source_type: str,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    origin: str | None = None,
    cited_by_count: int | None = None,
    url: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    metadata: dict | None = None,
) -> SourceRow:
    """Synchronous counterpart of create_or_get_source for use inside sync orchestrator nodes."""
    from sqlalchemy.orm import Session  # noqa: F401 – used in type hint

    existing = _get_source_by_canonical_id_sync(session, tenant_id=tenant_id, canonical_id=canonical_id)
    now = _now_utc()
    metadata_json = dict(metadata or {})

    if existing:
        updated = False
        if title and existing.title != title:
            existing.title = title
            updated = True
        normalized_authors = _normalize_author_names(authors)
        current_authors = list_source_author_names(existing)
        if normalized_authors and current_authors != normalized_authors:
            replace_source_authors(existing, normalized_authors)
            updated = True
        if year and existing.year != year:
            existing.year = year
            updated = True
        if venue and existing.venue != venue:
            existing.venue = venue
            updated = True
        if origin and existing.origin != origin:
            existing.origin = origin
            updated = True
        if cited_by_count is not None and (
            existing.cited_by_count is None or cited_by_count > existing.cited_by_count
        ):
            existing.cited_by_count = cited_by_count
            updated = True
        if url and existing.url != url:
            existing.url = url
            updated = True
        if doi and get_source_identifier(existing, "doi") != doi:
            set_source_identifier(existing, "doi", doi)
            updated = True
        if arxiv_id and get_source_identifier(existing, "arxiv_id") != arxiv_id:
            set_source_identifier(existing, "arxiv_id", arxiv_id)
            updated = True
        if metadata_json:
            merged = dict(existing.metadata_json or {})
            for key, value in metadata_json.items():
                if value is None:
                    continue
                if key not in merged or merged[key] in (None, "", [], {}):
                    merged[key] = value
            if merged != existing.metadata_json:
                existing.metadata_json = merged
                updated = True
        if updated:
            existing.updated_at = now
            session.flush()
        return existing

    source = SourceRow(
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        source_type=source_type,
        title=title,
        year=year,
        venue=venue,
        origin=origin,
        cited_by_count=cited_by_count,
        url=url,
        metadata_json=metadata_json,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(source)
        session.flush()
    except IntegrityError:
        # Another worker inserted the same canonical_id concurrently.
        # Roll back the savepoint and return the row they inserted.
        session.rollback()
        race_winner = _get_source_by_canonical_id_sync(session, tenant_id=tenant_id, canonical_id=canonical_id)
        if race_winner is None:
            raise  # genuine integrity error unrelated to this insert
        return race_winner
    replace_source_authors(source, authors)
    set_source_identifier(source, "doi", doi)
    set_source_identifier(source, "arxiv_id", arxiv_id)
    session.flush()
    return source


def source_to_api_payload(source: SourceRow) -> dict[str, object]:
    return {
        "id": source.id,
        "tenant_id": source.tenant_id,
        "canonical_id": source.canonical_id,
        "source_type": source.source_type,
        "title": source.title,
        "authors_json": list_source_author_names(source),
        "year": source.year,
        "url": source.url,
        "metadata_json": source.metadata_json or {},
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


__all__ = [
    "create_or_get_source",
    "create_or_get_source_sync",
    "get_source",
    "get_source_by_canonical_id",
    "get_source_identifier",
    "list_source_author_names",
    "replace_source_authors",
    "set_source_identifier",
    "source_to_api_payload",
]
