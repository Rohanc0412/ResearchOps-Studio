from __future__ import annotations

import sys
import types
import unittest.mock as mock

from llm import OpenAICompatibleClient


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
    from llm import BedrockClient

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
    assert payload["inferenceConfig"]["temperature"] == 0.3
    assert payload["system"] == [{"text": "be helpful"}]
    assert payload["messages"] == [
        {"role": "user", "content": [{"text": "hello"}]}
    ]


def test_bedrock_generate_accepts_response_format_without_failing():
    from llm import BedrockClient

    client = BedrockClient(
        model_name="amazon.nova-lite-v1:0",
        region_name="us-east-1",
    )

    with mock.patch.object(
        client,
        "_converse",
        return_value={
            "output": {"message": {"content": [{"text": '{"ok": true}'}]}},
            "usage": {"inputTokens": 3, "outputTokens": 2},
        },
    ) as mock_converse:
        result = client.generate(
            "hello",
            system="return json",
            response_format="json",
        )

    assert result == '{"ok": true}'
    assert "system" in mock_converse.call_args.kwargs
    assert "valid JSON" in mock_converse.call_args.kwargs["system"][0]["text"]


def test_bedrock_generate_uses_mocked_runtime_client_execution_path():
    from llm import BedrockClient

    runtime_client = mock.MagicMock()
    runtime_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "ok"}]}},
        "usage": {"inputTokens": 4, "outputTokens": 2},
    }

    fake_boto3 = types.SimpleNamespace(client=mock.MagicMock(return_value=runtime_client))
    fake_config_module = types.SimpleNamespace(Config=mock.MagicMock(return_value=object()))

    with mock.patch.dict(
        sys.modules,
        {
            "boto3": fake_boto3,
            "botocore": types.SimpleNamespace(config=fake_config_module),
            "botocore.config": fake_config_module,
        },
    ):
        client = BedrockClient(
            model_name="amazon.nova-lite-v1:0",
            region_name="us-east-1",
        )
        result = client.generate("hello", system="be helpful", max_tokens=64, temperature=0.1)

    assert result == "ok"
    fake_boto3.client.assert_called_once()
    runtime_client.converse.assert_called_once()
    payload = runtime_client.converse.call_args.kwargs
    assert payload["modelId"] == "amazon.nova-lite-v1:0"
    assert payload["inferenceConfig"]["maxTokens"] == 64
