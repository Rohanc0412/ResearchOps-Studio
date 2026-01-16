from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
def health(request: Request) -> dict[str, str | None]:
    return {
        "status": "ok",
        "version": request.app.state.git_sha,
        "time": datetime.now(timezone.utc).isoformat(),
    }
