"""FastAPI dependency injection helpers for the API service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from db.session import session_scope
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_scope(request.app.state.SessionLocal) as session:
        yield session


DBDep = Annotated[AsyncSession, Depends(get_db)]
