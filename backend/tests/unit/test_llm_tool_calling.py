from __future__ import annotations

import json
import unittest.mock as mock

import pytest

from llm import LLMError, OpenAICompatibleClient

CLIENT = OpenAICompatibleClient(
    base_url="https://openrouter.ai/api",
    api_key="test-key",
    model_name="openai/gpt-4o-mini",
)

TOOL_DEF = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def _make_plain_response(content: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": content, "tool_calls": None}}]
    }
    return resp


def _make_tool_call_response(query: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": query}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    return resp


def test_generate_with_tools_returns_plain_text():
    messages = [{"role": "user", "content": "Hello"}]
    with mock.patch("httpx.post", return_value=_make_plain_response("Hi there!")):
        result = CLIENT.generate_with_tools(messages, TOOL_DEF)
    assert result["content"] == "Hi there!"
    assert not result.get("tool_calls")


def test_generate_with_tools_returns_tool_call():
    messages = [{"role": "user", "content": "What happened today?"}]
    with mock.patch("httpx.post", return_value=_make_tool_call_response("today's news")):
        result = CLIENT.generate_with_tools(messages, TOOL_DEF)
    assert result.get("tool_calls") is not None
    assert result["tool_calls"][0]["function"]["name"] == "web_search"
    args = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert args["query"] == "today's news"


def test_generate_with_tools_raises_llm_error_on_empty_choices():
    messages = [{"role": "user", "content": "Hello"}]
    bad_resp = mock.MagicMock()
    bad_resp.raise_for_status.return_value = None
    bad_resp.json.return_value = {"choices": []}
    with mock.patch("httpx.post", return_value=bad_resp):
        with pytest.raises(LLMError, match="missing choices"):
            CLIENT.generate_with_tools(messages, TOOL_DEF)


def test_generate_with_tools_sends_tools_in_payload():
    messages = [{"role": "user", "content": "Hello"}]
    with mock.patch("httpx.post", return_value=_make_plain_response("ok")) as mock_post:
        CLIENT.generate_with_tools(messages, TOOL_DEF)
    payload = mock_post.call_args[1]["json"]
    assert "tools" in payload
    assert payload["tools"] == TOOL_DEF
    assert payload["messages"] == messages
