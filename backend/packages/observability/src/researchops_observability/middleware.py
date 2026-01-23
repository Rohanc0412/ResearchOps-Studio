from __future__ import annotations

import uuid
import logging
import time
from collections.abc import Callable

from fastapi import Request, Response

from researchops_observability.context import bind


logger = logging.getLogger(__name__)


def request_id_middleware(app_name: str) -> Callable:
    async def _middleware(request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        bind(request_id=rid, service=app_name)
        start = time.perf_counter()
        query = request.url.query or None
        logger.info(
            "Request started",
            extra={
                "event": "http.request",
                "method": request.method,
                "path": request.url.path,
                "query": query,
                "status_code": None,
                "duration_ms": None,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "response_bytes": None,
            },
        )
        try:
            response: Response = await call_next(request)
        except Exception:
            _bind_optional_ids(request)
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "Request failed",
                extra={
                    "event": "http.request",
                    "method": request.method,
                    "path": request.url.path,
                    "query": query,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                    "response_bytes": None,
                },
            )
            raise

        response.headers["x-request-id"] = rid

        content_length = response.headers.get("content-length")
        response_bytes = int(content_length) if content_length and content_length.isdigit() else None
        _bind_optional_ids(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Request completed",
            extra={
                "event": "http.request",
                "method": request.method,
                "path": request.url.path,
                "query": query,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "response_bytes": response_bytes,
            },
        )
        return response

    return _middleware


def _bind_optional_ids(request: Request) -> None:
    identity = getattr(request.state, "identity", None)
    tenant_id = getattr(identity, "tenant_id", None) if identity else None
    run_id = request.path_params.get("run_id") if request.path_params else None
    fields: dict[str, str | None] = {}
    if tenant_id:
        fields["tenant_id"] = tenant_id
    if run_id is not None:
        fields["run_id"] = str(run_id)
    if fields:
        bind(**fields)

