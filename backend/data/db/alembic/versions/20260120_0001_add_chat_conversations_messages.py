"""Add chat conversation and message tables.

Revision ID: 20260120_0001
Revises: 20260119_0001
Create Date: 2026-01-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260120_0001"
down_revision = "20260119_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("pending_action_json", postgresql.JSONB(), nullable=True),
        sa.Column("last_action_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_chat_conversations_tenant_id_id"),
    )
    op.create_index("ix_chat_conversations_tenant_id", "chat_conversations", ["tenant_id"])
    op.create_index(
        "ix_chat_conversations_tenant_project_id",
        "chat_conversations",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_chat_conversations_tenant_created_by",
        "chat_conversations",
        ["tenant_id", "created_by_user_id"],
    )
    op.create_index(
        "ix_chat_conversations_tenant_last_message_at",
        "chat_conversations",
        ["tenant_id", "last_message_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("client_message_id", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["chat_conversations.tenant_id", "chat_conversations.id"],
            name="fk_chat_messages_tenant_conversation",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_chat_messages_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "client_message_id",
            name="uq_chat_messages_client_message_id",
        ),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    op.create_index(
        "ix_chat_messages_tenant_conversation_created_at",
        "chat_messages",
        ["tenant_id", "conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_tenant_conversation_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_tenant_last_message_at", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_tenant_created_by", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_tenant_project_id", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_tenant_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")
