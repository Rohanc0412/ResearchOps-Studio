from __future__ import annotations

import contextvars

request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
service: contextvars.ContextVar[str | None] = contextvars.ContextVar("service", default=None)


def bind(**fields: str | None) -> None:
    if "request_id" in fields:
        request_id.set(fields["request_id"])
    if "tenant_id" in fields:
        tenant_id.set(fields["tenant_id"])
    if "run_id" in fields:
        run_id.set(fields["run_id"])
    if "service" in fields:
        service.set(fields["service"])

