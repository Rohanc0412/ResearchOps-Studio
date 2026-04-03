from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from observability.logging_setup import PrettyFormatter
from observability.middleware import request_id_middleware


def _make_record(
    message: str,
    *,
    level: int = logging.INFO,
    exc_info=None,
    **extra,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_pretty_formatter_renders_compact_context_and_visible_extras() -> None:
    formatter = PrettyFormatter()
    record = _make_record(
        "Request finished: GET /chat -> 200 in 84ms",
        service="api",
        request_id="1234567890abcdef",
        run_id="run-abcdef123456",
        tenant_id="tenant-12345678",
        method="GET",
        path="/chat",
        status_code=200,
        duration_ms=84,
        preview="trimmed preview",
        ignored_field="hidden",
    )

    rendered = formatter.format(record)

    assert "INFO Request finished: GET /chat -> 200 in 84ms" in rendered
    assert "method=GET" in rendered
    assert "path=/chat" in rendered
    assert "status=200" in rendered
    assert "in 84ms" in rendered
    assert "preview=trimmed preview" in rendered
    assert "[svc:api req:12345678 run:runabcde tenant:tenant12]" in rendered
    assert "ignored_field" not in rendered
    assert "extra={" not in rendered


def test_pretty_formatter_includes_traceback_for_exceptions() -> None:
    formatter = PrettyFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = _make_record("Research run failed", level=logging.ERROR, exc_info=sys.exc_info())
    rendered = formatter.format(record)
    assert "ERROR Research run failed" in rendered
    assert "Traceback" in rendered
    assert "RuntimeError: boom" in rendered


@pytest.mark.asyncio
async def test_request_middleware_logs_human_readable_messages(caplog: pytest.LogCaptureFixture) -> None:
    middleware = request_id_middleware("api")
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"verbose=1",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    request = Request(scope)
    request.state.identity = SimpleNamespace(tenant_id="tenant-12345678")

    async def call_next(_request: Request) -> Response:
        return Response(content="ok", status_code=204, headers={"content-length": "2"})

    with caplog.at_level(logging.INFO):
        response = await middleware(request, call_next)

    assert response.status_code == 204
    messages = [record.getMessage() for record in caplog.records]
    assert "Request started: GET /health" in messages
    assert "Request finished: GET /health -> 204" in messages[1]
