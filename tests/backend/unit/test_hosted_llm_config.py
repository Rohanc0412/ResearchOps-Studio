from __future__ import annotations


def test_get_llm_client_uses_openai_env_fallbacks(monkeypatch):
    monkeypatch.delenv("HOSTED_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("HOSTED_LLM_API_KEY", raising=False)
    monkeypatch.delenv("HOSTED_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    from llm import get_llm_client

    client = get_llm_client("hosted", None)

    assert client is not None
    assert client.base_url == "https://api.openai.com"
    assert client.api_key == "test-openai-key"
    assert client.model_name == "openai/gpt-4o-mini"


def test_resolve_model_for_stage_falls_back_to_default_hosted_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.delenv("HOSTED_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    from llm import resolve_model_for_stage

    assert resolve_model_for_stage("draft", None, "hosted", None) == "openai/gpt-4o-mini"


def test_explain_llm_error_surfaces_quota_issue():
    from llm import explain_llm_error

    message = explain_llm_error(
        'Hosted LLM request failed: HTTP 429. Response: {"status":"RESOURCE_EXHAUSTED","message":"quota exceeded"}'
    )

    assert "quota or rate limits" in message
    assert "retry later" in message.lower()
