from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health(request: Request) -> dict[str, str | None]:
    engine = getattr(request.app.state, "engine", None)
    db_ok = True
    schema_ok: bool | None = None
    if engine is not None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                dialect_name = engine.dialect.name
                if dialect_name == "postgresql":
                    schema_ok = (
                        (await conn.execute(text("SELECT to_regclass('public.alembic_version')")))
                        .scalar_one()
                        is not None
                    )
                elif dialect_name == "sqlite":
                    schema_ok = True
        except Exception:
            db_ok = False
            schema_ok = False

    payload = {
        "status": "ok",
        "version": request.app.state.git_sha,
        "time": datetime.now(UTC).isoformat(),
        "db_ok": str(bool(db_ok)).lower(),
        "schema_ok": None if schema_ok is None else str(bool(schema_ok)).lower(),
    }

    if not db_ok or schema_ok is False:
        return JSONResponse(payload, status_code=503)

    return payload
