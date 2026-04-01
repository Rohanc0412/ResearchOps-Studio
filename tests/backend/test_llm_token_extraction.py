import pytest
from unittest.mock import MagicMock, patch


def _make_response(content: str, prompt_tokens: int, completion_tokens: int):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_generate_returns_content_and_tokens():
    from llm import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://fake",
        api_key="key",
        model_name="test-model",
    )
    fake_response = _make_response("hello world", prompt_tokens=10, completion_tokens=5)

    with patch("httpx.post", return_value=fake_response):
        result = client.generate("say hello")

    assert result == "hello world"
    assert client.last_prompt_tokens == 10
    assert client.last_completion_tokens == 5
