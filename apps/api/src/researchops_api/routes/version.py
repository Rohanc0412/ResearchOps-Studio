from __future__ import annotations

from fastapi import APIRouter, Request

from researchops_core import SERVICE_API

router = APIRouter()


@router.get("/version")
def version(request: Request) -> dict[str, str | None]:
    return {
        "name": SERVICE_API,
        "git_sha": request.app.state.git_sha,
        "build_time": request.app.state.build_time,
    }

