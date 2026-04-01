from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from db.models.chat_conversations import ChatConversationRow
from db.repositories.chat import create_conversation, get_conversation_for_user, list_conversations_for_user


@pytest.mark.asyncio
async def test_chat_conversation_visibility_is_scoped_to_user() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(ChatConversationRow.__table__.create)

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
