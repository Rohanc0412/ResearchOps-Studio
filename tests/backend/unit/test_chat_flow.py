from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from app import create_app
from core.auth.config import get_auth_config
from core.settings import get_settings
from db.models.chat_conversations import ChatConversationRow
from db.models.chat_messages import ChatMessageRow
from db.models.runs import RunRow
from db.session import session_scope
from fastapi.testclient import TestClient
from routes import chat_titles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)


@pytest.fixture()
def api_client(tmp_path):
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
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
    force_pipeline: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
):
    payload = {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "message": message,
        "client_message_id": client_message_id,
        "force_pipeline": force_pipeline,
    }
    if llm_provider is not None:
        payload["llm_provider"] = llm_provider
    if llm_model is not None:
        payload["llm_model"] = llm_model
    return client.post("/chat/send", json=payload)


def _parse_send_response(resp) -> dict:
    """Parse a /send response that may be plain JSON or SSE text/event-stream.
    For SSE, returns the payload of the 'answer' event."""
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        return resp.json()
    current_event = ""
    for line in resp.text.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: ") and current_event == "answer":
            return json.loads(line[len("data: "):])
    raise ValueError("SSE stream contained no 'answer' event")


@asynccontextmanager
async def _fresh_session_scope():
    async_url = _TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url)
    session_local = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_scope(session_local) as session:
            yield session
    finally:
        await engine.dispose()


def _latest_run_question(app, project_id: str) -> str:
    async def _run():
        async with _fresh_session_scope() as session:
            run = (await session.execute(
                select(RunRow)
                .where(RunRow.project_id == UUID(project_id))
                .order_by(RunRow.created_at.desc())
            )).scalars().first()
            assert run is not None
            return run.question

    return asyncio.run(_run())


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


def test_quick_answer_prompt_does_not_duplicate_current_user_message(api_client, monkeypatch) -> None:
    client, _ = api_client
    project_id = _create_project(client, "Prompt Dedup Project")
    conversation_id = _create_conversation(client, project_id)
    captured_prompts: list[str] = []

    class StubLLM:
        def generate(self, prompt, **_kwargs):
            captured_prompts.append(prompt)
            return "One answer only."

    import routes.chat as chat_route

    monkeypatch.setattr(chat_route, "get_llm_client", lambda *_args, **_kwargs: StubLLM())

    first = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Give me a quick overview.",
        client_message_id="prompt-dedup-0",
    )
    assert first.status_code == 200

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Summarize the project status.",
        client_message_id="prompt-dedup-1",
    )
    assert resp.status_code == 200
    assert _parse_send_response(resp)["assistant_message"]["content_text"] == "One answer only."
    assert len(captured_prompts) == 2
    assert captured_prompts[1].count("User: Give me a quick overview.") == 1
    assert captured_prompts[1].count("User: Summarize the project status.") == 1


def test_conversation_title_refreshes_after_four_user_turns(api_client, monkeypatch) -> None:
    client, _ = api_client
    project_id = _create_project(client, "Retitle Project")
    conversation_id = _create_conversation(client, project_id)

    def fake_generate_title_with_llm(history, report_title, llm_provider, llm_model):
        return "Retitled After Four Turns"

    monkeypatch.setattr(chat_titles, "_generate_title_with_llm", fake_generate_title_with_llm)

    prompts = [
        "Explain machine learning simply.",
        "Give me a practical example.",
        "What are the main risks?",
        "Summarize the tradeoffs in one paragraph.",
    ]

    for idx, prompt in enumerate(prompts, start=1):
        resp = _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message=prompt,
            client_message_id=f"title-{idx}",
        )
        assert resp.status_code == 200

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.title == "Retitled After Four Turns"

    asyncio.run(_check())


def test_pipeline_offer_sets_pending(api_client) -> None:
    client, _ = api_client
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

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is not None

    asyncio.run(_check())


def test_pipeline_yes_starts_run(api_client) -> None:
    client, _ = api_client
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

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is None
            run = (await session.execute(
                select(RunRow).where(RunRow.project_id == UUID(project_id))
            )).scalar_one()
            assert run is not None

    asyncio.run(_check())


def test_force_pipeline_uses_prior_substantive_prompt_for_generic_trigger(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Force Pipeline Project")
    conversation_id = _create_conversation(client, project_id)

    detailed_prompt = (
        "Run the full research report on adoption risks of autonomous coding agents "
        "in enterprise teams, with citations and evidence."
    )
    generic_trigger = "Run the research report now."

    first = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=detailed_prompt,
        client_message_id="force-1",
    )
    assert first.status_code == 200

    second = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=generic_trigger,
        client_message_id="force-2",
        force_pipeline=True,
    )
    assert second.status_code == 200
    assert second.json()["assistant_message"]["type"] == "run_started"
    assert second.json()["assistant_message"]["content_json"]["question"] == detailed_prompt
    run_id = second.json()["assistant_message"]["content_json"]["run_id"]

    assert _latest_run_question(app, project_id) == detailed_prompt
    run_resp = client.get(f"/runs/{run_id}")
    assert run_resp.status_code == 200
    assert run_resp.json()["question"] == detailed_prompt


@pytest.mark.parametrize(
    "generic_trigger",
    [
        "Run the research report now.",
        "RUN THE RESEARCH REPORT NOW!!!",
        "create the detailed research report now",
        "Go ahead",
    ],
)
def test_force_pipeline_generic_trigger_variants_use_prior_prompt(
    api_client, generic_trigger: str
) -> None:
    client, app = api_client
    project_id = _create_project(client, f"Generic Variants Project {generic_trigger}")
    conversation_id = _create_conversation(client, project_id)
    detailed_prompt = (
        "Assess the security, governance, and reliability risks of autonomous coding "
        "agents in enterprise teams, with citations and evidence."
    )

    first = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=detailed_prompt,
        client_message_id=f"variant-seed-{generic_trigger}",
    )
    assert first.status_code == 200

    second = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=generic_trigger,
        client_message_id=f"variant-run-{generic_trigger}",
        force_pipeline=True,
    )
    assert second.status_code == 200
    assert second.json()["assistant_message"]["content_json"]["question"] == detailed_prompt
    assert _latest_run_question(app, project_id) == detailed_prompt


def test_force_pipeline_uses_most_recent_substantive_prompt(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Most Recent Prompt Project")
    conversation_id = _create_conversation(client, project_id)
    first_prompt = "Create a cited report on governance risks of autonomous coding agents."
    second_prompt = (
        "Create a cited report on operational rollout risks of autonomous coding agents "
        "in enterprise teams."
    )

    assert (
        _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message=first_prompt,
            client_message_id="recent-1",
        ).status_code
        == 200
    )
    assert (
        _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message="thanks",
            client_message_id="recent-ack",
        ).status_code
        == 200
    )
    assert (
        _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message=second_prompt,
            client_message_id="recent-2",
        ).status_code
        == 200
    )

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Run the research report now.",
        client_message_id="recent-run",
        force_pipeline=True,
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["content_json"]["question"] == second_prompt
    assert _latest_run_question(app, project_id) == second_prompt


def test_force_pipeline_ignores_non_substantive_prior_messages(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Non Substantive Project")
    conversation_id = _create_conversation(client, project_id)

    assert (
        _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message="hello",
            client_message_id="noise-1",
        ).status_code
        == 200
    )
    assert (
        _send_message(
            client,
            conversation_id=conversation_id,
            project_id=project_id,
            message="thanks",
            client_message_id="noise-2",
        ).status_code
        == 200
    )

    generic_trigger = "Run the research report now."
    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=generic_trigger,
        client_message_id="noise-run",
        force_pipeline=True,
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["content_json"]["question"] == generic_trigger
    assert _latest_run_question(app, project_id) == generic_trigger


def test_force_pipeline_does_not_reuse_prompt_from_other_conversation(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Conversation Isolation Project")
    source_conversation_id = _create_conversation(client, project_id)
    target_conversation_id = _create_conversation(client, project_id)
    detailed_prompt = (
        "Create a cited report on adoption risks of autonomous coding agents in "
        "enterprise teams."
    )
    generic_trigger = "Run the research report now."

    seed = _send_message(
        client,
        conversation_id=source_conversation_id,
        project_id=project_id,
        message=detailed_prompt,
        client_message_id="isolation-seed",
    )
    assert seed.status_code == 200

    resp = _send_message(
        client,
        conversation_id=target_conversation_id,
        project_id=project_id,
        message=generic_trigger,
        client_message_id="isolation-run",
        force_pipeline=True,
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["content_json"]["question"] == generic_trigger
    assert _latest_run_question(app, project_id) == generic_trigger


def test_force_pipeline_direct_detailed_prompt_uses_same_question(api_client) -> None:
    client, app = api_client
    project_id = _create_project(client, "Direct Force Pipeline Project")
    conversation_id = _create_conversation(client, project_id)
    detailed_prompt = (
        "Evaluate the operational, security, and governance risks of autonomous coding "
        "agents in enterprise teams, with citations and evidence."
    )

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message=detailed_prompt,
        client_message_id="direct-run",
        force_pipeline=True,
    )
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["content_json"]["question"] == detailed_prompt
    assert _latest_run_question(app, project_id) == detailed_prompt


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
    assert _parse_send_response(resp)["assistant_message"]["type"] == "chat"

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is None

    asyncio.run(_check())


def test_action_tokens_override_ambiguity(api_client) -> None:
    client, _ = api_client
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

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is None

    asyncio.run(_check())


def test_ambiguous_twice_defaults_quick_answer(api_client) -> None:
    client, _ = api_client
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
    assert "quick chat answer" in _parse_send_response(first)["assistant_message"]["content_text"].lower()

    second = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="ok",
        client_message_id="amb-2",
    )
    assert second.status_code == 200
    assert _parse_send_response(second)["assistant_message"]["type"] == "chat"

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is None

    asyncio.run(_check())


def test_new_topic_clears_pending(api_client) -> None:
    client, _ = api_client
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
    assert _parse_send_response(resp)["assistant_message"]["type"] == "chat"

    async def _check():
        async with _fresh_session_scope() as session:
            convo = (await session.execute(
                select(ChatConversationRow).where(ChatConversationRow.id == UUID(conversation_id))
            )).scalar_one()
            assert convo.pending_action_json is None

    asyncio.run(_check())


def test_client_message_id_idempotency(api_client) -> None:
    client, _ = api_client
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

    async def _check():
        async with _fresh_session_scope() as session:
            rows = (
                await session.execute(
                    select(ChatMessageRow).where(ChatMessageRow.client_message_id == "dup-1")
                )
            ).scalars().all()
            assert len(rows) == 1

    asyncio.run(_check())


def test_run_start_idempotency(api_client) -> None:
    client, _ = api_client
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

    async def _check():
        async with _fresh_session_scope() as session:
            runs = (await session.execute(
                select(RunRow).where(RunRow.project_id == UUID(project_id))
            )).scalars().all()
            assert len(runs) == 1

    asyncio.run(_check())


def test_project_run_setup_accepts_bedrock_provider(api_client) -> None:
    client, _ = api_client
    project_id = _create_project(client, "Bedrock Setup Project")

    resp = client.post(
        f"/projects/{project_id}/runs",
        json={
            "question": "Prepare a cited report on evaluation benchmarks for coding agents.",
            "client_request_id": "bedrock-run-1",
            "llm_provider": "bedrock",
        },
    )

    assert resp.status_code == 200
    run_resp = client.get(f"/runs/{resp.json()['run_id']}")
    assert run_resp.status_code == 200
    usage = run_resp.json()["usage"]
    assert usage["llm_provider"] == "bedrock"
    assert usage["llm_model"] == "amazon.nova-lite-v1:0"


def test_bedrock_pending_action_replay_preserves_provider(api_client) -> None:
    client, _ = api_client
    project_id = _create_project(client, "Bedrock Pending Project")
    conversation_id = _create_conversation(client, project_id)

    offer = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="Create a literature review with citations about Bedrock model evaluation.",
        client_message_id="bedrock-offer-1",
        llm_provider="bedrock",
    )
    assert offer.status_code == 200
    assert offer.json()["assistant_message"]["type"] == "pipeline_offer"
    assert offer.json()["pending_action"]["llm_provider"] == "bedrock"

    accept = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="__ACTION__:run_pipeline",
        client_message_id="bedrock-accept-1",
    )
    assert accept.status_code == 200
    assert accept.json()["assistant_message"]["type"] == "run_started"

    run_id = accept.json()["assistant_message"]["content_json"]["run_id"]
    run_resp = client.get(f"/runs/{run_id}")
    assert run_resp.status_code == 200
    usage = run_resp.json()["usage"]
    assert usage["llm_provider"] == "bedrock"


def test_bedrock_quick_answer_skips_tool_calling_when_tools_are_unavailable(
    api_client, monkeypatch
) -> None:
    client, _ = api_client
    project_id = _create_project(client, "Bedrock Quick Answer Project")
    conversation_id = _create_conversation(client, project_id)

    class StubBedrockLLM:
        def __init__(self):
            self.prompts: list[str] = []

        def generate(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            return "Bedrock quick answer."

    stub = StubBedrockLLM()

    import routes.chat as chat_route

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(chat_route, "get_llm_client", lambda *_args, **_kwargs: stub)

    resp = _send_message(
        client,
        conversation_id=conversation_id,
        project_id=project_id,
        message="What is Amazon Bedrock?",
        client_message_id="bedrock-chat-1",
        llm_provider="bedrock",
    )

    assert resp.status_code == 200
    assert _parse_send_response(resp)["assistant_message"]["content_text"] == "Bedrock quick answer."
    assert len(stub.prompts) == 1
