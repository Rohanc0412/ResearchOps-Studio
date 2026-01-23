from __future__ import annotations

import os

from fastapi.testclient import TestClient

from researchops_api import create_app
from researchops_core.auth.config import get_auth_config
from researchops_core.settings import get_settings


def test_healthz_ok() -> None:
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    get_auth_config.cache_clear()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
