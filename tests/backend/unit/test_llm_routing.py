from __future__ import annotations

import os
import pytest


def test_balanced_profile_keys_are_valid_stage_names():
    """BALANCED_PROFILE must cover all 5 known stage names."""
    from llm import BALANCED_PROFILE
    assert set(BALANCED_PROFILE.keys()) == {"retrieve", "outline", "draft", "evaluate", "repair"}


def test_balanced_profile_tier_values():
    """Each stage must map to 'cheap' or 'capable'."""
    from llm import BALANCED_PROFILE
    assert BALANCED_PROFILE["retrieve"] == "cheap"
    assert BALANCED_PROFILE["outline"] == "capable"
    assert BALANCED_PROFILE["draft"] == "capable"
    assert BALANCED_PROFILE["evaluate"] == "cheap"
    assert BALANCED_PROFILE["repair"] == "capable"


def test_resolve_uses_stage_models_override(monkeypatch):
    """Explicit stage_models entry wins over balanced profile."""
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("outline", {"outline": "openai/gpt-4o"}, "hosted", None)
    assert result == "openai/gpt-4o"


def test_resolve_falls_back_to_balanced_capable(monkeypatch):
    """Null stage_models entry uses balanced profile -> LLM_MODEL_CAPABLE."""
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("outline", {"outline": None}, "hosted", None)
    assert result == "capable-model"


def test_resolve_falls_back_to_balanced_cheap(monkeypatch):
    """Null stage_models entry uses balanced profile -> LLM_MODEL_CHEAP for cheap stages."""
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("retrieve", None, "hosted", None)
    assert result == "cheap-model"


def test_resolve_capable_falls_back_to_cheap_when_unset(monkeypatch):
    """If LLM_MODEL_CAPABLE is unset, capable tier falls back to LLM_MODEL_CHEAP."""
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.setenv("LLM_MODEL_CHEAP", "only-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", None, "hosted", None)
    assert result == "only-model"


def test_resolve_falls_back_to_hosted_llm_model(monkeypatch):
    """When no tier env vars set, falls back to HOSTED_LLM_MODEL."""
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.setenv("HOSTED_LLM_MODEL", "fallback-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", None, "hosted", None)
    assert result == "fallback-model"


def test_resolve_uses_run_level_model_override(monkeypatch):
    """run-level llm_model is used when stage_models is empty and no tier env vars."""
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.delenv("HOSTED_LLM_MODEL", raising=False)
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", {}, "hosted", "run-level-model")
    assert result == "run-level-model"


def test_get_llm_client_for_stage_accepts_stage_models(monkeypatch):
    """get_llm_client_for_stage() accepts stage_models kwarg without error."""
    monkeypatch.setenv("HOSTED_LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("HOSTED_LLM_API_KEY", "test-key")
    monkeypatch.setenv("HOSTED_LLM_MODEL", "default-model")
    from llm import get_llm_client_for_stage
    client = get_llm_client_for_stage("draft", "hosted", None, stage_models={"draft": None})
    assert client is not None
    assert client.model_name == "default-model"


def test_operator_env_var_beats_stage_models(monkeypatch):
    """LLM_MODEL_{STAGE} operator env var wins over stage_models user override."""
    monkeypatch.setenv("HOSTED_LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("HOSTED_LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_DRAFT", "operator-model")
    from llm import get_llm_client_for_stage
    client = get_llm_client_for_stage("draft", "hosted", None, stage_models={"draft": "user-model"})
    assert client is not None
    assert client.model_name == "operator-model"
