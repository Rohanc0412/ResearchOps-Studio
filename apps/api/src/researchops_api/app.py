from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from db.init_db import init_db
from db.session import create_db_engine, create_sessionmaker
from researchops_core import SERVICE_API, get_settings
from researchops_observability import configure_logging, request_id_middleware
from researchops_observability.context import bind

from researchops_api.middlewares.auth import init_auth_runtime
from researchops_api.routes.health import router as health_router
from researchops_api.routes.runs import router as runs_router
from researchops_api.routes.version import router as version_router
from researchops_api.routes.auth import router as auth_router
from researchops_api.routes.tenants import router as tenants_router

logger = logging.getLogger(__name__)


def _git_sha() -> str | None:
    sha = os.getenv("GIT_SHA")
    if sha:
        return sha
    head = Path(".git/HEAD")
    if not head.exists():
        return None
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref_path = Path(".git") / ref.split(" ", 1)[1]
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        return ref[:12]
    except Exception:
        return None


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_API, level=settings.log_level)
    bind(service=SERVICE_API)

    engine = create_db_engine(settings)
    SessionLocal = create_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _.state.auth_runtime = init_auth_runtime()
        init_db(engine)
        yield

    app = FastAPI(title="ResearchOps Studio API", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.git_sha = _git_sha()
    app.state.build_time = datetime.now(timezone.utc).isoformat()

    app.middleware("http")(request_id_middleware(SERVICE_API))

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(auth_router)
    app.include_router(tenants_router)
    app.include_router(runs_router)

    logger.info("api_started", extra={"port": settings.api_port})
    return app
