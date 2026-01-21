from __future__ import annotations

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from researchops_api import create_app
from researchops_core.auth.config import get_auth_config
from researchops_core.settings import get_settings
from db.models.chat_conversations import ChatConversationRow
from db.models.chat_messages import ChatMessageRow
from db.models.runs import RunRow
from db.session import session_scope


@pytest.fixture()
def api_client(tmp_path):
    db_path = tmp_path / "chat.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "true"
    os.environ["LLM_PROVIDER"] = "none"
    get_auth_config.cache_clear()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client, app


def _create_project(client: TestClient, name: str = "Chat Project") -> str:
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 200
    data = resp.json()
    return data["id"]


def _create_conversation(client: TestClient, project_id: str) -> str:
    resp = client.post(
        "/chat/conversations", json={"project_id": project_id, "title": "Chat 1"}
    )
    assert resp.status_code == 200
    return resp.json()["conversation_id"]


def _send_message(
    client: TestClient,
    *,
    conversation_id: str,
    project_id: str,
    message: str,
    client_message_id: str,
):
    return client.post(
        "/chat/send",
        json={
            "conversation_id": conversation_id,
            "project_id": project_id,
            "message": message,
            "client_message_id": client_message_id,
        },
    )


def test_chat_message_persistence(api_client) -> None:
    client, _ = api_client
    project_id = _create_project(client)
    conversation_id = _create_conversation(client, project_id)

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Hello there",
        client_message_id="m1",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_message"]["role"] == "user"
    assert data["assistant_message"]["role"] == "assistant"

    history = client.get(f"/chat/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    items = history.json()["items"]
    assert len(items) == 2
    assert items[0]["role"] == "user"
    assert items[1]["role"] == "assistant"


def test_pipeline_offer_sets_pending(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Pipeline Project")
    conversation_id = _create_conversation(client, project_id)

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Give me a literature review with citations on LLM safety.",
        client_message_id="offer-1",
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["type"] == "pipeline_offer"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is not None


def test_pipeline_yes_starts_run(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Yes Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Please provide a systematic review with sources.",
        client_message_id="offer-yes",
    )
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:run_pipeline",
        client_message_id="yes-1",
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["type"] == "run_started"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is None
        run = session.execute(select(RunRow).where(RunRow.project_id == UUID(project_id))).scalar_one()
        assert run is not None


def test_pipeline_no_returns_quick_answer(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "No Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Compare recent papers on retrieval augmented generation with citations.",
        client_message_id="offer-no",
    )
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:quick_answer",
        client_message_id="no-1",
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["type"] == "chat"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is None


def test_action_tokens_override_ambiguity(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Action Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Please provide a report with references about AI safety.",
        client_message_id="offer-action",
    )
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:quick_answer",
        client_message_id="action-1",
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["type"] == "chat"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is None


def test_ambiguous_twice_defaults_quick_answer(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Ambiguous Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Produce a literature review with citations on graph neural networks.",
        client_message_id="offer-amb",
    )
    first = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="ok",
        client_message_id="amb-1",
    )
    assert first.status_code == 200
    assert "quick chat answer" in first.json()["assistant_message"]["content_text"].lower()

    second = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="ok",
        client_message_id="amb-2",
    )
    assert second.status_code == 200
    assert second.json()["assistant_message"]["type"] == "chat"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is None


def test_new_topic_clears_pending(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "New Topic Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Write a survey of recent LLM papers with citations.",
        client_message_id="offer-topic",
    )
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="What is a transformer model?",
        client_message_id="topic-1",
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["type"] == "chat"

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        convo = session.execute(
            select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
        ).scalar_one()
        assert convo.pending_action_json is None


def test_client_message_id_idempotency(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Idempotent Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Hello",
        client_message_id="dup-1",
    )
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Hello again",
        client_message_id="dup-1",
    )
    assert resp.status_code == 200
    assert resp.json()["idempotent_replay"] is True

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        rows = (
            session.execute(
                select(ChatMessageRow).where(ChatMessageRow.client_message_id == "dup-1")
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


def test_run_start_idempotency(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Run Idempotent Project")
    conversation_id = _create_conversation(client, project_id)

    _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Provide a literature review with citations on neural rendering.",
        client_message_id="offer-run",
    )
    first = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:run_pipeline",
        client_message_id="run-1",
    )
    assert first.status_code == 200
    run_id = first.json()["assistant_message"]["content_json"]["run_id"]

    second = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:run_pipeline",
        client_message_id="run-2",
    )
    assert second.status_code == 200
    assert second.json()["assistant_message"]["content_json"]["run_id"] == run_id

    SessionLocal = app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        runs = session.execute(select(RunRow).where(RunRow.project_id == UUID(project_id))).scalars().all()
        assert len(runs) == 1
