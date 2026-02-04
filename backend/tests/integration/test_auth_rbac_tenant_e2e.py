from __future__ import annotations

import os
from fastapi.testclient import TestClient
from researchops_api import create_app
from researchops_core.settings import get_settings
from researchops_core.auth.config import get_auth_config


def test_auth_rbac_and_tenant_isolation_end_to_end(tmp_path) -> None:
    db_path = tmp_path / "e2e.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["WORKER_POLL_SECONDS"] = "0.01"

    os.environ["AUTH_REQUIRED"] = "true"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["AUTH_JWT_SECRET"] = "test-secret"
    os.environ["AUTH_JWT_ISSUER"] = "researchops-api"

    get_settings.cache_clear()
    get_auth_config.cache_clear()

    app = create_app()

    with TestClient(app) as client:
        # Public endpoint works without token
        assert client.get("/health").status_code == 200

        # Protected endpoint blocks without token
        assert client.get("/me").status_code == 401

        reg_a = client.post(
            "/auth/register",
            json={
                "username": "alice",
                "password": "password123",
                "tenant_id": "00000000-0000-0000-0000-0000000000aa",
            },
        ).json()
        headers_a = {"Authorization": f"Bearer {reg_a['access_token']}"}

        me = client.get("/me", headers=headers_a).json()
        assert me["tenant_id"] == "00000000-0000-0000-0000-0000000000aa"
        assert "owner" in me["roles"]

        project = client.post("/projects", headers=headers_a, json={"name": "RBAC Project"}).json()
        project_id = project["id"]
        run = client.post(
            f"/projects/{project_id}/runs",
            headers=headers_a,
            json={"question": "Summarize LLMs", "output_type": "report"},
        ).json()
        run_id = run.get("id") or run.get("run_id")
        assert run_id is not None

        run_state = client.get(f"/runs/{run_id}", headers=headers_a).json()
        assert run_state["status"] in {"created", "queued", "running"}

        # Cross-tenant access is blocked (404, because tenant-scoped query)
        reg_b = client.post(
            "/auth/register",
            json={
                "username": "bob",
                "password": "password123",
                "tenant_id": "00000000-0000-0000-0000-0000000000bb",
            },
        ).json()
        headers_b = {"Authorization": f"Bearer {reg_b['access_token']}"}
        assert client.get(f"/runs/{run_id}", headers=headers_b).status_code == 404
