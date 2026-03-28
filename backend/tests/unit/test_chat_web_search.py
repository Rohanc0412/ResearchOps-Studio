from __future__ import annotations

import json
import os
import uuid
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(tool_call_response: dict | None = None, plain_text: str = "Final answer"):
    """Return a mock LLM client."""
    client = mock.MagicMock()
    client.generate_with_tools = mock.MagicMock()

    plain_msg = {"role": "assistant", "content": plain_text, "tool_calls": None}

    if tool_call_response is not None:
        client.generate_with_tools.side_effect = [tool_call_response, plain_msg]
    else:
        client.generate_with_tools.return_value = plain_msg

    return client


def _tool_call_msg(query: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": query}),
                },
            }
        ],
    }


def _call_generate_quick_answer(
    client,
    message: str = "What is the weather today?",
    tavily_key: str = "test-tavily-key",
) -> str:
    """Return just the answer text from the generator (backward-compat helper)."""
    import routes.chat as chat_mod

    fake_history: list = []

    with (
        mock.patch.dict(os.environ, {"TAVILY_API_KEY": tavily_key}),
        mock.patch("routes.chat.get_llm_client", return_value=client),
    ):
        events = list(
            chat_mod._generate_quick_answer(
                history=fake_history,
                tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                conversation_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                message=message,
                llm_provider=None,
                llm_model=None,
            )
        )
    answer_events = [data for event_type, data in events if event_type == "answer"]
    return answer_events[0] if answer_events else ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plain_text_response_no_search():
    """When LLM returns plain text, Tavily is never called."""
    client = _make_client(plain_text="The sky is blue.")

    with mock.patch("routes.chat.search") as mock_search:
        result = _call_generate_quick_answer(client)

    assert result == "The sky is blue."
    mock_search.assert_not_called()


def test_tool_call_triggers_search_and_returns_final_answer():
    """When LLM returns a tool call, search is executed and final answer returned."""
    client = _make_client(
        tool_call_response=_tool_call_msg("today weather"),
        plain_text="It is sunny today.",
    )

    fake_results = [
        mock.MagicMock(title="Weather", url="https://weather.com", snippet="Sunny, 22°C"),
    ]

    with mock.patch("routes.chat.search", return_value=fake_results) as mock_search:
        result = _call_generate_quick_answer(client, message="What is the weather today?")

    assert result == "It is sunny today."
    mock_search.assert_called_once_with("today weather")
    # Second LLM call should have tool result in messages
    second_call_messages = client.generate_with_tools.call_args_list[1][0][0]
    tool_result_msg = next(m for m in second_call_messages if m.get("role") == "tool")
    tool_content = json.loads(tool_result_msg["content"])
    assert tool_content[0]["title"] == "Weather"


def test_no_api_key_skips_tools():
    """When TAVILY_API_KEY is not set, tools are omitted and generate_with_tools not called."""
    client = mock.MagicMock()
    client.generate.return_value = "Plain answer without tools."

    with mock.patch("routes.chat.search") as mock_search:
        result = _call_generate_quick_answer(client, tavily_key="")

    assert result == "Plain answer without tools."
    client.generate.assert_called_once()
    client.generate_with_tools.assert_not_called()
    mock_search.assert_not_called()


def test_tavily_error_falls_back_gracefully():
    """When Tavily raises, the tool result is empty and LLM still produces a final answer."""
    client = _make_client(
        tool_call_response=_tool_call_msg("something"),
        plain_text="I could not find current info, but here is what I know.",
    )

    with mock.patch("routes.chat.search", side_effect=Exception("timeout")):
        result = _call_generate_quick_answer(client)

    assert "could not find" in result
    second_call_messages = client.generate_with_tools.call_args_list[1][0][0]
    tool_result_msg = next(m for m in second_call_messages if m.get("role") == "tool")
    assert tool_result_msg["content"] == "[]"


def test_llm_error_returns_fallback_string():
    """When LLM raises LLMError, the function returns the standard fallback string."""
    from llm import LLMError
    client = mock.MagicMock()
    client.generate_with_tools.side_effect = LLMError("API down")

    result = _call_generate_quick_answer(client)

    assert "trouble" in result


# ---------------------------------------------------------------------------
# New generator tests
# ---------------------------------------------------------------------------

def _collect_events(client, message="What is the weather today?", tavily_key="test-key"):
    """Call _generate_quick_answer and collect all (event_type, data) tuples."""
    import routes.chat as chat_mod

    with (
        mock.patch.dict(os.environ, {"TAVILY_API_KEY": tavily_key}),
        mock.patch("routes.chat.get_llm_client", return_value=client),
        mock.patch("routes.chat.search", return_value=[]) as mock_search,
    ):
        events = list(
            chat_mod._generate_quick_answer(
                history=[],
                tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                conversation_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                message=message,
                llm_provider=None,
                llm_model=None,
            )
        )
    return events, mock_search


def test_generator_emits_answer_without_search():
    client = _make_client()  # no tool calls
    events, mock_search = _collect_events(client)
    assert events == [("answer", "Final answer")]
    mock_search.assert_not_called()


def test_generator_emits_status_then_answer_with_search():
    client = _make_client(tool_call_response=_tool_call_msg("weather today"))
    events, mock_search = _collect_events(client)
    types = [e[0] for e in events]
    assert types == ["status", "answer"]
    assert events[0][1] == "Searching the web..."
    mock_search.assert_called_once_with("weather today")
