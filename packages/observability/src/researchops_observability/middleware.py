from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Request, Response

from researchops_observability.context import bind


def request_id_middleware(app_name: str) -> Callable:
    async def _middleware(request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        bind(request_id=rid, service=app_name)
        response: Response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    return _middleware

