import os
import importlib
import pytest


def test_langfuse_disabled_when_no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # Force re-import after env change
    import observability.langfuse_setup as lf
    importlib.reload(lf)
    assert lf.langfuse_enabled() is False


def test_langfuse_enabled_when_keys_set(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    import observability.langfuse_setup as lf
    importlib.reload(lf)
    assert lf.langfuse_enabled() is True


def test_get_langfuse_client_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    import observability.langfuse_setup as lf
    importlib.reload(lf)
    assert lf.get_langfuse_client() is None
