from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from db.models.audit_logs import AuditLogRow
from researchops_core.auth.identity import Identity
from researchops_observability.context import request_id as request_id_ctx


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def write_audit_log(
    *,
    db: Session,
    identity: Identity,
    action: str,
    target_type: str,
    target_id: str | None,
    metadata: dict[str, Any] | None,
    request: Request | None = None,
) -> None:
    ip = None
    user_agent = None
    req_id = request_id_ctx.get()
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        req_id = request.headers.get("x-request-id") or req_id

    db.add(
        AuditLogRow(
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
            ip=ip,
            user_agent=user_agent,
            request_id=req_id,
            created_at=_now_utc(),
        )
    )
