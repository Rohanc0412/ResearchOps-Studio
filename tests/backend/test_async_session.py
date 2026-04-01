import pytest
from unittest.mock import MagicMock
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def test_create_db_engine_returns_async_engine():
    from unittest.mock import patch
    settings = MagicMock()
    settings.database_url = "postgresql+psycopg://user:pass@localhost/db"

    with patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create:
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_create.return_value = mock_engine
        from db.session import create_db_engine
        engine = create_db_engine(settings)
        mock_create.assert_called_once()
        call_url = mock_create.call_args[0][0]
        assert "asyncpg" in call_url


def test_session_url_substitution():
    """psycopg URL is rewritten to asyncpg."""
    from db.session import _async_url
    assert _async_url("postgresql+psycopg://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _async_url("postgresql+psycopg2://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _async_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
