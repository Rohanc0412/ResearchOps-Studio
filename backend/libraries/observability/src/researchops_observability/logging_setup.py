from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from researchops_observability.context import request_id, run_id, service, tenant_id


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class JsonFormatter(logging.Formatter):
    """
    JSON formatter (best for production).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_iso(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, "service", None),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
            "run_id": getattr(record, "run_id", None),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extras: dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k in LOGRECORD_BUILTIN_KEYS:
                continue
            if k in ("request_id", "tenant_id", "run_id", "service"):
                continue
            extras[k] = _to_jsonable(_redact_key_value(k, v))

        if extras:
            payload["extra"] = extras

        return json.dumps(payload, ensure_ascii=False)


class PrettyFormatter(logging.Formatter):
    """
    Pretty formatter (best for local dev).
    Includes a short local timestamp so logs are easier to scan.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = _local_time_short()

        rid = getattr(record, "request_id", None)
        tid = getattr(record, "tenant_id", None)
        ruid = getattr(record, "run_id", None)
        svc = getattr(record, "service", None)

        base = (
            f"{ts} "
            f"[{record.levelname}] "
            f"svc={svc} req={rid} tenant={tid} run={ruid} "
            f"{record.name}: {record.getMessage()}"
        )

        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)

        extras: dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k in LOGRECORD_BUILTIN_KEYS:
                continue
            if k in ("request_id", "tenant_id", "run_id", "service"):
                continue
            extras[k] = _to_jsonable(_redact_key_value(k, v))

        if extras:
            base += f" extra={extras}"

        return base


def setup_logging(app_service_name: str) -> None:
    """
    Configure logging once per process.
    Safe to call multiple times (idempotent).

    Supports:
    - Console logging (pretty or json)
    - Optional file logging (RotatingFileHandler) if LOG_FILE_PATH is set
    """
    root = logging.getLogger()

    # If already configured by us, do not reconfigure handlers.
    # We still update the bound service name to keep context accurate.
    if getattr(root, "_configured_by_researchops", False):
        from researchops_observability.context import bind

        bind(service=app_service_name)
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = (os.getenv("LOG_FORMAT") or "pretty").lower()

    root.setLevel(level)
    root.handlers.clear()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(ContextFilter())
    console_handler.setFormatter(JsonFormatter() if log_format == "json" else PrettyFormatter())
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

        # File logs should almost always be JSON for easier analysis
        file_handler.setFormatter(JsonFormatter())

        root.addHandler(file_handler)

    # Let uvicorn logs flow into our formatting (no duplicate uvicorn handlers)
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Bind service name once
    from researchops_observability.context import bind

    bind(service=app_service_name)

    # Mark configured so repeated calls won't wipe handlers
    root._configured_by_researchops = True  # type: ignore[attr-defined]

    logging.getLogger(__name__).info(
        "Logging is initialized",
        extra={
            "event": "logging.init",
            "log_level": level_name,
            "log_format": log_format,
            "file_logging_enabled": bool(log_file_path),
            "log_file_path": log_file_path or None,
        },
    )
