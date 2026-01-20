from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from researchops_observability.context import bind as bind_context
from researchops_observability.context import request_id, run_id, service, tenant_id


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_time_short() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return str(value)


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_CYAN = "\033[96m"


class ConsoleFormatter(logging.Formatter):
    """Human-readable colored console formatter for development."""

    LEVEL_COLORS = {
        "DEBUG": Colors.DIM,
        "INFO": Colors.BRIGHT_CYAN,
        "WARNING": Colors.BRIGHT_YELLOW,
        "ERROR": Colors.RED,
        "CRITICAL": Colors.RED + Colors.BOLD,
    }

    # Special message styling
    MSG_STYLES = {
        "run_queued": (Colors.BRIGHT_GREEN, "RUN QUEUED"),
        "run_processing_start": (Colors.BRIGHT_BLUE, "RUN STARTED"),
        "run_processing_complete": (Colors.BRIGHT_GREEN, "RUN COMPLETED"),
        "run_status_transition": (Colors.CYAN, "STATUS"),
        "job_claimed": (Colors.YELLOW, "JOB CLAIMED"),
        "job_succeeded": (Colors.BRIGHT_GREEN, "JOB DONE"),
        "job_failed": (Colors.RED, "JOB FAILED"),
        "project_run_enqueued": (Colors.BRIGHT_GREEN, "RUN QUEUED"),
        "artifact_written": (Colors.MAGENTA, "ARTIFACT"),
        "stage_start": (Colors.BLUE, "STAGE START"),
        "stage_finish": (Colors.GREEN, "STAGE DONE"),
        "llm_request": (Colors.MAGENTA, "LLM REQUEST"),
        "llm_response": (Colors.MAGENTA, "LLM RESPONSE"),
    }

    def format(self, record: logging.LogRecord) -> str:
        time_str = _utc_time_short()
        level = record.levelname
        level_color = self.LEVEL_COLORS.get(level, "")
        msg = record.getMessage()

        # Check for special message types
        style_color, style_label = self.MSG_STYLES.get(msg, (None, None))

        # Build extra info string
        extras = []
        skip_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module", "msecs",
            "message", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName", "taskName",
        }
        for key, value in record.__dict__.items():
            if key in skip_keys:
                continue
            if value is not None:
                extras.append(f"{key}={value}")

        extra_str = f" {Colors.DIM}| {' '.join(extras)}{Colors.RESET}" if extras else ""

        # Format based on message type
        if style_color and style_label:
            return (
                f"{Colors.DIM}{time_str}{Colors.RESET} "
                f"{style_color}{Colors.BOLD}[{style_label}]{Colors.RESET}"
                f"{extra_str}"
            )

        # Default format
        run_id_val = run_id.get()
        run_prefix = f"{Colors.DIM}[run:{run_id_val[:8]}]{Colors.RESET} " if run_id_val else ""

        return (
            f"{Colors.DIM}{time_str}{Colors.RESET} "
            f"{level_color}{level:7}{Colors.RESET} "
            f"{run_prefix}"
            f"{msg}"
            f"{extra_str}"
        )


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
        reserved = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
        }
        for key, value in record.__dict__.items():
            if key in reserved or key in payload:
                continue
            payload[key] = _to_jsonable(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str, *, level: str = "INFO", json_format: bool | None = None) -> None:
    """Configure logging with either JSON or human-readable console format.

    Args:
        service_name: Name of the service for log context.
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, use JSON format. If False, use console format.
                     If None (default), auto-detect based on LOG_FORMAT env var
                     or default to console format for development.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    # Auto-detect format: use console by default, JSON if LOG_FORMAT=json
    if json_format is None:
        json_format = os.getenv("LOG_FORMAT", "console").lower() == "json"

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    root.addHandler(handler)

    bind_context(service=service_name)


def bind_log_context(*, tenant_id_value: str | None = None, run_id_value: str | None = None) -> None:
    bind_context(tenant_id=tenant_id_value, run_id=run_id_value)

