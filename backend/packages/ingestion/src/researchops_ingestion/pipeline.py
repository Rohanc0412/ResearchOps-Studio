"""
Core evidence ingestion pipeline.

This module orchestrates the full ingestion flow:
1. Create or find source
2. Create snapshot with blob storage
3. Sanitize snapshot content
4. Chunk into snippets with offsets
5. Generate embeddings for each snippet
6. Store everything in database

Multi-tenant safe: all operations are scoped to tenant_id.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from db.models import SnapshotRow, SnippetEmbeddingRow, SnippetRow, SourceRow
from researchops_ingestion.chunking import chunk_text
from researchops_ingestion.embeddings import EmbeddingProvider
from researchops_ingestion.sanitize import sanitize_text



def _now_utc() -> datetime:
    return datetime.now(UTC)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_hex(text.encode("utf-8"))


class IngestionResult:
    """Result of ingesting a source into evidence storage."""

    def __init__(
        self,
        source: SourceRow,
        snapshot: SnapshotRow,
        snippets: list[SnippetRow],
        embeddings: list[SnippetEmbeddingRow],
    ):
        self.source = source
        self.snapshot = snapshot
        self.snippets = snippets
        self.embeddings = embeddings

    @property
    def source_id(self) -> UUID:
        return self.source.id

    @property
    def snapshot_id(self) -> UUID:
        return self.snapshot.id

    @property
    def snippet_count(self) -> int:
        return len(self.snippets)

    @property
    def has_risk_flags(self) -> bool:
        """Check if any snippet has risk flags set."""
        return any(
            snippet.risk_flags_json.get("prompt_injection")
            or snippet.risk_flags_json.get("excessive_repetition")
            for snippet in self.snippets
        )


def create_or_get_source(
    *,
    session: Session,
    tenant_id: UUID,
    canonical_id: str,
    source_type: str,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    url: str | None = None,
    pdf_url: str | None = None,
    metadata: dict | None = None,
) -> SourceRow:
    """
    Create a new source or return existing one by canonical_id.

    Args:
        session: Database session
        tenant_id: Tenant ID for multi-tenant isolation
        canonical_id: Unique identifier for source (e.g., DOI, arXiv ID, URL)
        source_type: Type of source (e.g., "paper", "webpage", "book")
        title: Source title
        authors: List of author names
        year: Publication year
        url: Source URL
        pdf_url: Optional PDF URL (stored in metadata if provided)
        metadata: Additional metadata JSON

    Returns:
        SourceRow (existing or newly created)
    """
    # Try to find existing source
    existing = (
        session.query(SourceRow)
        .filter(
            SourceRow.tenant_id == tenant_id,
            SourceRow.canonical_id == canonical_id,
        )
        .first()
    )

    if existing:
        updated = False
        if url and not existing.url:
            existing.url = url
            updated = True
        if pdf_url:
            existing_meta = dict(existing.metadata_json or {})
            if existing_meta.get("pdf_url") != pdf_url:
                existing_meta["pdf_url"] = pdf_url
                existing.metadata_json = existing_meta
                updated = True
        if updated:
            existing.updated_at = _now_utc()
            session.flush()
        return existing

    # Create new source
    now = _now_utc()
    metadata_json = dict(metadata or {})
    if pdf_url:
        metadata_json.setdefault("pdf_url", pdf_url)

    source = SourceRow(
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        source_type=source_type,
        title=title,
        authors_json=authors or [],
        year=year,
        url=url,
        metadata_json=metadata_json,
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    session.flush()
    return source


def create_snapshot(
    *,
    session: Session,
    tenant_id: UUID,
    source_id: UUID,
    raw_content: str,
    content_type: str | None = None,
    blob_ref: str,
    metadata: dict | None = None,
) -> SnapshotRow:
    """
    Create a new immutable snapshot of source content.

    Args:
        session: Database session
        tenant_id: Tenant ID
        source_id: Parent source ID
        raw_content: Raw text content (for hash calculation)
        content_type: MIME type or content type hint
        blob_ref: Reference to stored blob (e.g., "s3://bucket/key" or "inline://...")
        metadata: Additional metadata JSON

    Returns:
        SnapshotRow
    """
    # Calculate hash and size
    content_bytes = raw_content.encode("utf-8")
    sha256 = _sha256_hex(content_bytes)
    size_bytes = len(content_bytes)

    # Determine snapshot version (incremental per source)
    max_version = (
        session.query(SnapshotRow.snapshot_version)
        .filter(
            SnapshotRow.tenant_id == tenant_id,
            SnapshotRow.source_id == source_id,
        )
        .order_by(SnapshotRow.snapshot_version.desc())
        .first()
    )
    version = (max_version[0] + 1) if max_version else 1

    now = _now_utc()
    snapshot = SnapshotRow(
        tenant_id=tenant_id,
        source_id=source_id,
        snapshot_version=version,
        retrieved_at=now,
        content_type=content_type,
        blob_ref=blob_ref,
        sha256=sha256,
        size_bytes=size_bytes,
        metadata_json=metadata or {},
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def ingest_snapshot(
    *,
    session: Session,
    tenant_id: UUID,
    snapshot: SnapshotRow,
    raw_content: str,
    embedding_provider: EmbeddingProvider,
    max_chunk_chars: int = 1000,
    overlap_chars: int = 100,
) -> IngestionResult:
    """
    Ingest a snapshot: sanitize, chunk, embed, and store snippets.

    Args:
        session: Database session
        tenant_id: Tenant ID
        snapshot: Snapshot to ingest
        raw_content: Raw text content from snapshot
        embedding_provider: Provider for generating embeddings
        max_chunk_chars: Maximum characters per chunk
        overlap_chars: Overlap between chunks

    Returns:
        IngestionResult with created snippets and embeddings
    """
    # Step 1: Sanitize text
    sanitized = sanitize_text(raw_content)
    clean_text = sanitized["text"]
    risk_flags = sanitized["risk_flags"]

    # Step 2: Chunk text
    chunks = chunk_text(clean_text, max_chars=max_chunk_chars, overlap_chars=overlap_chars)

    # Step 3: Create snippet rows
    snippets: list[SnippetRow] = []
    for idx, chunk in enumerate(chunks):
        snippet = SnippetRow(
            tenant_id=tenant_id,
            snapshot_id=snapshot.id,
            snippet_index=idx,
            text=chunk["text"],
            char_start=chunk["char_start"],
            char_end=chunk["char_end"],
            token_count=chunk["token_count"],
            sha256=_sha256_text(chunk["text"]),
            risk_flags_json=risk_flags,  # Same risk flags for all snippets from this snapshot
            created_at=_now_utc(),
        )
        session.add(snippet)
        snippets.append(snippet)

    session.flush()  # Get snippet IDs

    # Step 4: Generate embeddings
    snippet_texts = [s.text for s in snippets]
    embedding_vectors = embedding_provider.embed_texts(snippet_texts)

    # Step 5: Store embeddings
    embeddings: list[SnippetEmbeddingRow] = []
    for snippet, vector in zip(snippets, embedding_vectors):
        embedding = SnippetEmbeddingRow(
            tenant_id=tenant_id,
            snippet_id=snippet.id,
            embedding_model=embedding_provider.model_name,
            dims=embedding_provider.dimensions,
            embedding=vector,
            created_at=_now_utc(),
        )
        session.add(embedding)
        embeddings.append(embedding)

    session.flush()

    # Return result
    source = session.query(SourceRow).filter(SourceRow.id == snapshot.source_id).one()
    return IngestionResult(
        source=source,
        snapshot=snapshot,
        snippets=snippets,
        embeddings=embeddings,
    )


def ingest_source(
    *,
    session: Session,
    tenant_id: UUID,
    canonical_id: str,
    source_type: str,
    raw_content: str,
    embedding_provider: EmbeddingProvider,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    url: str | None = None,
    pdf_url: str | None = None,
    content_type: str | None = None,
    blob_ref: str | None = None,
    metadata: dict | None = None,
    max_chunk_chars: int = 1000,
    overlap_chars: int = 100,
) -> IngestionResult:
    """
    Full ingestion pipeline: create source, snapshot, snippets, and embeddings.

    This is the main entry point for ingesting evidence.

    Args:
        session: Database session
        tenant_id: Tenant ID
        canonical_id: Unique source identifier
        source_type: Type of source
        raw_content: Raw text content to ingest
        embedding_provider: Provider for generating embeddings
        title: Source title
        authors: Author names
        year: Publication year
        url: Source URL
        pdf_url: Optional PDF URL (stored in metadata if provided)
        content_type: Content MIME type
        blob_ref: Blob storage reference (if None, uses inline reference)
        metadata: Additional metadata
        max_chunk_chars: Maximum characters per chunk
        overlap_chars: Overlap between chunks

    Returns:
        IngestionResult with all created entities

    Example:
        >>> from researchops_ingestion.embeddings import StubEmbeddingProvider
        >>> provider = StubEmbeddingProvider()
        >>> result = ingest_source(
        ...     session=session,
        ...     tenant_id=tenant_id,
        ...     canonical_id="arxiv:2401.12345",
        ...     source_type="paper",
        ...     raw_content="<p>This is a research paper...</p>",
        ...     embedding_provider=provider,
        ...     title="Example Paper",
        ... )
        >>> result.snippet_count > 0
        True
    """
    # Step 1: Create or get source
    source = create_or_get_source(
        session=session,
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        source_type=source_type,
        title=title,
        authors=authors,
        year=year,
        url=url,
        pdf_url=pdf_url,
        metadata=metadata,
    )

    # Step 2: Create snapshot
    if blob_ref is None:
        # Use inline reference for testing/small content
        blob_ref = f"inline://{source.id}/{_now_utc().isoformat()}"

    snapshot = create_snapshot(
        session=session,
        tenant_id=tenant_id,
        source_id=source.id,
        raw_content=raw_content,
        content_type=content_type,
        blob_ref=blob_ref,
        metadata=metadata,
    )

    # Step 3: Ingest snapshot (sanitize, chunk, embed)
    result = ingest_snapshot(
        session=session,
        tenant_id=tenant_id,
        snapshot=snapshot,
        raw_content=raw_content,
        embedding_provider=embedding_provider,
        max_chunk_chars=max_chunk_chars,
        overlap_chars=overlap_chars,
    )
    return result
