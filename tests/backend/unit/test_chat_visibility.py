from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import db.models  # noqa: F401 — ensure all model tables are registered
from db.models.chat_conversations import ChatConversationRow
from db.repositories.chat import create_conversation, get_conversation_for_user, list_conversations_for_user

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


@pytest.mark.asyncio
async def test_chat_conversation_visibility_is_scoped_to_user() -> None:
    from db.init_db import init_db as _init_db

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)

    AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    async with AsyncSessionLocal() as session:
        convo_u1 = await create_conversation(
            session=session,
            tenant_id=tenant_id,
            project_id=None,
            created_by_user_id="user-1",
            title="u1 chat",
        )
        convo_u2 = await create_conversation(
            session=session,
            tenant_id=tenant_id,
            project_id=None,
            created_by_user_id="user-2",
            title="u2 chat",
        )
        await session.commit()

        rows = await list_conversations_for_user(
            session=session,
            tenant_id=tenant_id,
            created_by_user_id="user-1",
            project_id=None,
            limit=50,
            cursor=None,
        )
        assert [r.id for r in rows] == [convo_u1.id]

        assert (
            await get_conversation_for_user(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo_u1.id,
                created_by_user_id="user-1",
            )
            is not None
        )
        assert (
            await get_conversation_for_user(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo_u2.id,
                created_by_user_id="user-1",
            )
            is None
        )

    await engine.dispose()
