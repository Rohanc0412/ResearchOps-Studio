from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from researchops_observability.context import bind as bind_context
from researchops_observability.context import request_id, run_id, service, tenant_id


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_iso(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": service.get(),
            "request_id": request_id.get(),
            "tenant_id": tenant_id.get(),
            "run_id": run_id.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str, *, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    bind_context(service=service_name)


def bind_log_context(*, tenant_id_value: str | None = None, run_id_value: str | None = None) -> None:
    bind_context(tenant_id=tenant_id_value, run_id=run_id_value)

