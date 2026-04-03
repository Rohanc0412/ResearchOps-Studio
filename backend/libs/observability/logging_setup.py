from __future__ import annotations

import logging
import os
import pathlib
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from observability.context import request_id, run_id, service, tenant_id


def _local_time_short() -> str:
    """
    Human-friendly local time for pretty logs.
    Example: 14:05:33
    """
    return datetime.now().strftime("%H:%M:%S")


SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "cookie",
}


def _redact_key_value(k: str, v: Any) -> Any:
    key = (k or "").lower()
    if key in SENSITIVE_KEYS:
        return "***REDACTED***"
    return v


def _max_log_string_len() -> int:
    raw = os.getenv("LOG_MAX_STRING")
    if raw is None or not raw.strip():
        return 2000
    try:
        value = int(raw)
    except ValueError:
        return 2000
    return value


def _clamp_string(s: str, max_len: int | None = None) -> str:
    limit = _max_log_string_len() if max_len is None else max_len
    if limit <= 0:
        return s
    if len(s) <= limit:
        return s
    return s[:limit] + "...(truncated)"


def _to_jsonable(value: Any) -> Any:
    """
    Convert values into safe JSON-friendly data types, and avoid giant logs.
    """
    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        return _clamp_string(value)

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            out[ks] = _to_jsonable(_redact_key_value(ks, v))
        return out

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    return _clamp_string(str(value), max_len=2000)


class ContextFilter(logging.Filter):
    """
    Attach correlation IDs to every log record automatically.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        record.tenant_id = tenant_id.get()
        record.run_id = run_id.get()
        record.service = service.get()
        return True


LOGRECORD_BUILTIN_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
}

VISIBLE_EXTRA_KEYS = (
    "method",
    "path",
    "query",
    "status_code",
    "duration_ms",
    "stage",
    "step",
    "section_id",
    "current_stage",
    "max_iterations",
    "provider",
    "llm_provider",
    "llm_model",
    "model_name",
    "chars",
    "workers",
    "response_bytes",
    "query_count",
    "preview",
    "research_goal",
    "artifact_count",
    "reason",
    "status",
    "email_domain",
    "environment",
    "token_hash_prefix",
)
_CONTEXT_KEYS = ("service", "request_id", "run_id", "tenant_id")
_SHORT_ENABLE_RE = re.compile(r"[^a-zA-Z0-9]+")


def _short_id(value: Any, *, limit: int = 8) -> str | None:
    if value is None:
        return None
    cleaned = _SHORT_ENABLE_RE.sub("", str(value))
    if not cleaned:
        return None
    return cleaned[:limit]


def _iter_visible_extras(record: logging.LogRecord) -> list[tuple[str, Any]]:
    extras: list[tuple[str, Any]] = []
    for key in VISIBLE_EXTRA_KEYS:
        if key in _CONTEXT_KEYS:
            continue
        if key not in record.__dict__:
            continue
        value = _to_jsonable(_redact_key_value(key, record.__dict__[key]))
        if value in (None, "", [], {}):
            continue
        extras.append((key, value))
    return extras


def _build_context_block(record: logging.LogRecord) -> str:
    parts: list[str] = []
    service_name = getattr(record, "service", None)
    if service_name:
        parts.append(f"svc:{service_name}")
    request_ref = _short_id(getattr(record, "request_id", None))
    if request_ref:
        parts.append(f"req:{request_ref}")
    run_ref = _short_id(getattr(record, "run_id", None))
    if run_ref:
        parts.append(f"run:{run_ref}")
    tenant_ref = _short_id(getattr(record, "tenant_id", None))
    if tenant_ref:
        parts.append(f"tenant:{tenant_ref}")
    return f" [{' '.join(parts)}]" if parts else ""


def _format_extra_item(key: str, value: Any) -> str:
    if key == "status_code":
        return f"status={value}"
    if key == "duration_ms":
        return f"in {value}ms"
    if key == "section_id":
        return f"section={value}"
    if key == "current_stage":
        return f"current_stage={value}"
    if key == "max_iterations":
        return f"max_iterations={value}"
    if key == "response_bytes":
        return f"bytes={value}"
    if key == "chars":
        return f"chars={value}"
    if key == "preview":
        return f"preview={value}"
    if key == "query_count":
        return f"count={value}"
    return f"{key}={value}"


def _render_extra_suffix(record: logging.LogRecord) -> str:
    visible = _iter_visible_extras(record)
    if not visible:
        return ""
    return " " + " ".join(_format_extra_item(key, value) for key, value in visible)


class PrettyFormatter(logging.Formatter):
    """
    Pretty formatter (best for local dev).
    Includes a short local timestamp so logs are easier to scan.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = _local_time_short()
        message = record.getMessage().strip()
        base = f"{ts} {record.levelname} {message}{_render_extra_suffix(record)}{_build_context_block(record)}"

        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(app_service_name: str) -> None:
    """
    Configure logging once per process.
    Safe to call multiple times (idempotent).

    Supports:
    - Human-readable console logging
    - Optional file logging (RotatingFileHandler) if LOG_FILE_PATH is set
    """
    root = logging.getLogger()

    # If already configured by us, do not reconfigure handlers.
    # We still update the bound service name to keep context accurate.
    if getattr(root, "_configured_by_researchops", False):
        from observability.context import bind

        bind(service=app_service_name)
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = (os.getenv("LOG_FORMAT") or "pretty").lower()
    if log_format not in {"pretty", "text"}:
        log_format = "pretty"

    root.setLevel(level)
    root.handlers.clear()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(ContextFilter())
    console_handler.setFormatter(PrettyFormatter())
    root.addHandler(console_handler)

    # Optional file handler (enabled only if LOG_FILE_PATH is set)
    log_file_path = (os.getenv("LOG_FILE_PATH") or "").strip()
    if log_file_path:
        path = pathlib.Path(log_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        max_bytes = int((os.getenv("LOG_FILE_MAX_BYTES") or "10485760").strip())  # 10MB default
        backup_count = int((os.getenv("LOG_FILE_BACKUP_COUNT") or "5").strip())  # keep 5 backups

        file_handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.addFilter(ContextFilter())

        file_handler.setFormatter(PrettyFormatter())

        root.addHandler(file_handler)

    # Let uvicorn logs flow into our formatting (no duplicate uvicorn handlers)
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Bind service name once
    from observability.context import bind

    bind(service=app_service_name)

    # Mark configured so repeated calls won't wipe handlers
    root._configured_by_researchops = True  # type: ignore[attr-defined]

    logging.getLogger(__name__).info(
        "Logging initialized",
        extra={
            "event": "logging.init",
            "log_level": level_name,
            "log_format": log_format,
            "file_logging_enabled": bool(log_file_path),
            "log_file_path": log_file_path or None,
        },
    )
