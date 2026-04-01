from __future__ import annotations

import os

try:
    from langfuse import Langfuse
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False

_client: object | None = None


def langfuse_enabled() -> bool:
    """Return True only when both Langfuse credential env vars are set."""
    return bool(
        _LANGFUSE_AVAILABLE
        and os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )


def get_langfuse_client():
    """Return a singleton Langfuse client, or None when not configured."""
    global _client
    if not langfuse_enabled():
        return None
    if _client is None:
        kwargs: dict = {
            "public_key": os.environ["LANGFUSE_PUBLIC_KEY"],
            "secret_key": os.environ["LANGFUSE_SECRET_KEY"],
        }
        host = os.getenv("LANGFUSE_HOST")
        if host:
            kwargs["host"] = host
        _client = Langfuse(**kwargs)  # type: ignore[call-arg]
    return _client
