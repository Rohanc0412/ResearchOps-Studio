from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON

from db.models.base import Base

if TYPE_CHECKING:
    from db.models.source_authors import SourceAuthorRow
    from db.models.source_identifiers import SourceIdentifierRow
    from db.models.snapshots import SnapshotRow


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "canonical_id", name="uq_sources_tenant_canonical"),
        UniqueConstraint("tenant_id", "id", name="uq_sources_tenant_id_id"),
        Index("ix_sources_tenant_type_year", "tenant_id", "source_type", "year"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    canonical_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(Text(), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    venue: Mapped[str | None] = mapped_column(Text(), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cited_by_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    snapshots: Mapped[list[SnapshotRow]] = relationship(
        "SnapshotRow", back_populates="source", cascade="all, delete-orphan"
    )
    authors: Mapped[list[SourceAuthorRow]] = relationship(
        "SourceAuthorRow", back_populates="source", cascade="all, delete-orphan"
    )
    identifiers: Mapped[list[SourceIdentifierRow]] = relationship(
        "SourceIdentifierRow", back_populates="source", cascade="all, delete-orphan"
    )

    @property
    def authors_json(self) -> list[str]:
        rows = sorted(self.authors, key=lambda row: row.author_order)
        return [row.author_name for row in rows]

    @authors_json.setter
    def authors_json(self, values: list[str]) -> None:
        from db.models.source_authors import SourceAuthorRow

        self.authors = [
            SourceAuthorRow(
                tenant_id=self.tenant_id,
                author_order=index,
                author_name=str(value),
            )
            for index, value in enumerate(values or [])
            if str(value).strip()
        ]

    def _identifier_value(self, identifier_type: str) -> str | None:
        for row in self.identifiers:
            if row.identifier_type == identifier_type:
                return row.identifier_value
        return None

    def _set_identifier(self, identifier_type: str, identifier_value: str | None) -> None:
        rows = [row for row in self.identifiers if row.identifier_type != identifier_type]
        if identifier_value:
            from db.models.source_identifiers import SourceIdentifierRow

            rows.append(
                SourceIdentifierRow(
                    tenant_id=self.tenant_id,
                    identifier_type=identifier_type,
                    identifier_value=identifier_value,
                    is_primary=identifier_type == "canonical_id",
                )
            )
        self.identifiers = rows

    @property
    def doi(self) -> str | None:
        return self._identifier_value("doi")

    @doi.setter
    def doi(self, value: str | None) -> None:
        self._set_identifier("doi", value)

    @property
    def arxiv_id(self) -> str | None:
        return self._identifier_value("arxiv_id")

    @arxiv_id.setter
    def arxiv_id(self, value: str | None) -> None:
        self._set_identifier("arxiv_id", value)
