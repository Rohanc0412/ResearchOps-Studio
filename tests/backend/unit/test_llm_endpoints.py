from __future__ import annotations

import unittest.mock as mock

from llm import BedrockClient, OpenAICompatibleClient


def _ok_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    return resp


def test_generate_uses_standard_v1_chat_completions_url():
    client = OpenAICompatibleClient(
        base_url="https://openrouter.ai/api",
        api_key="test-key",
        model_name="test-model",
    )

    with mock.patch("httpx.post", return_value=_ok_response()) as mock_post:
        client.generate("hello")

    assert mock_post.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"


def test_generate_uses_gemini_openai_compat_chat_completions_url():
    client = OpenAICompatibleClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="test-key",
        model_name="gemini-2.5-flash",
    )

    with mock.patch("httpx.post", return_value=_ok_response()) as mock_post:
        client.generate("hello")

    assert (
        mock_post.call_args.args[0]
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def test_generate_strips_google_prefix_for_gemini_openai_compat():
    client = OpenAICompatibleClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="test-key",
        model_name="google/gemini-2.5-flash",
    )

    with mock.patch("httpx.post", return_value=_ok_response()) as mock_post:
        client.generate("hello")

    assert mock_post.call_args.kwargs["json"]["model"] == "gemini-2.5-flash"


def test_bedrock_generate_sends_converse_payload():
    client = BedrockClient(
        model_name="amazon.nova-lite-v1:0",
        region_name="us-east-1",
    )

    with mock.patch.object(
        client,
        "_converse",
        return_value={
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 3, "outputTokens": 2},
        },
    ) as mock_converse:
        result = client.generate("hello", system="be helpful", max_tokens=128, temperature=0.3)

    assert result == "ok"
    payload = mock_converse.call_args.kwargs
    assert payload["modelId"] == "amazon.nova-lite-v1:0"
    assert payload["inferenceConfig"]["maxTokens"] == 128
    assert payload["messages"][0]["role"] == "user"
