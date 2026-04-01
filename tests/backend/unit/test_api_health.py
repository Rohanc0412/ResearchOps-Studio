from __future__ import annotations

import os

from app import create_app
from core.auth.config import get_auth_config
from core.settings import get_settings
from fastapi.testclient import TestClient

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)


def test_healthz_ok() -> None:
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
    get_auth_config.cache_clear()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
