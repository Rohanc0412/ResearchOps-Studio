from __future__ import annotations

from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models.chat_conversations import ChatConversationRow
from db.services.chat import create_conversation, get_conversation_for_user, list_conversations_for_user


def test_chat_conversation_visibility_is_scoped_to_user() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    ChatConversationRow.__table__.create(engine)

    SessionLocal = sessionmaker(bind=engine, future=True)
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    with SessionLocal() as session:  # type: Session
        convo_u1 = create_conversation(
            session=session,
            tenant_id=tenant_id,
            project_id=None,
            created_by_user_id="user-1",
            title="u1 chat",
        )
        convo_u2 = create_conversation(
            session=session,
            tenant_id=tenant_id,
            project_id=None,
            created_by_user_id="user-2",
            title="u2 chat",
        )
        session.commit()

        rows = list_conversations_for_user(
            session=session,
            tenant_id=tenant_id,
            created_by_user_id="user-1",
            project_id=None,
            limit=50,
            cursor=None,
        )
        assert [r.id for r in rows] == [convo_u1.id]

        assert (
            get_conversation_for_user(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo_u1.id,
                created_by_user_id="user-1",
            )
            is not None
        )
        assert (
            get_conversation_for_user(
                session=session,
                tenant_id=tenant_id,
                conversation_id=convo_u2.id,
                created_by_user_id="user-1",
            )
            is None
        )
