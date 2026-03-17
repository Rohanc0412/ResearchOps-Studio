from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from researchops_core import SERVICE_API, get_settings
from researchops_observability import request_id_middleware

from db.init_db import init_db
from db.session import create_db_engine, create_sessionmaker
from researchops_api.middlewares.auth import init_auth_runtime
from researchops_api.routes.auth import router as auth_router
from researchops_api.routes.artifacts import router as artifacts_router
from researchops_api.routes.chat import router as chat_router
from researchops_api.routes.evidence import router as evidence_router
from researchops_api.routes.health import router as health_router
from researchops_api.routes.projects import router as projects_router
from researchops_api.routes.runs import router as runs_router



def _git_sha() -> str | None:
    sha = os.getenv("GIT_SHA")
    if sha:
        return sha
    for root in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        head = root / ".git" / "HEAD"
        if not head.exists():
            continue
        try:
            ref = head.read_text(encoding="utf-8").strip()
            if ref.startswith("ref: "):
                ref_path = head.parent / ref.split(" ", 1)[1]
                return ref_path.read_text(encoding="utf-8").strip()[:12]
            return ref[:12]
        except Exception:
            return None
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    engine = create_db_engine(settings)
    SessionLocal = create_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _.state.auth_runtime = init_auth_runtime()
        init_db(engine)
        yield

    app = FastAPI(title="ResearchOps Studio API", lifespan=lifespan)
    cors_origins = [
        o.strip()
        for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.git_sha = _git_sha()

    app.middleware("http")(request_id_middleware(SERVICE_API))

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(runs_router)
    app.include_router(projects_router)
    app.include_router(chat_router)
    app.include_router(evidence_router)
    app.include_router(artifacts_router)

    # Frontend uses `VITE_API_BASE_URL=/api` (Vite proxy doesn't rewrite paths), so
    # we expose the same routes under `/api/*` for compatibility.
    api = APIRouter(prefix="/api")
    api.include_router(health_router)
    api.include_router(auth_router)
    api.include_router(runs_router)
    api.include_router(projects_router)
    api.include_router(chat_router)
    api.include_router(evidence_router)
    api.include_router(artifacts_router)
    app.include_router(api)

    return app
