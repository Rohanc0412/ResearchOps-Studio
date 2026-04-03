from __future__ import annotations

import os
from uuid import uuid4

from app import create_app
from core.auth.config import get_auth_config
from core.settings import get_settings
from fastapi.testclient import TestClient

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)


def test_auth_rbac_and_tenant_isolation_end_to_end(tmp_path) -> None:
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
    os.environ["WORKER_POLL_SECONDS"] = "0.01"

    os.environ["AUTH_REQUIRED"] = "true"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["AUTH_JWT_SECRET"] = "test-secret-with-sufficient-length-32"
    os.environ["AUTH_JWT_ISSUER"] = "researchops-api"

    get_settings.cache_clear()
    get_auth_config.cache_clear()

    app = create_app()

    # Use uuid-based usernames/emails to avoid unique-constraint conflicts across runs.
    run_id_suffix = uuid4().hex[:8]
    username_a = f"alice-{run_id_suffix}"
    email_a = f"alice-{run_id_suffix}@example.com"
    username_b = f"bob-{run_id_suffix}"
    email_b = f"bob-{run_id_suffix}@example.com"

    with TestClient(app) as client:
        # Public endpoint works without token
        assert client.get("/health").status_code == 200

        # Protected endpoint blocks without token
        assert client.get("/me").status_code == 401

        reg_a = client.post(
            "/auth/register",
            json={
                "username": username_a,
                "email": email_a,
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
                "username": username_b,
                "email": email_b,
                "password": "password123",
                "tenant_id": "00000000-0000-0000-0000-0000000000bb",
            },
        ).json()
        headers_b = {"Authorization": f"Bearer {reg_b['access_token']}"}
        assert client.get(f"/runs/{run_id}", headers=headers_b).status_code == 404


def test_register_duplicate_email_returns_email_specific_error() -> None:
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
    os.environ["AUTH_REQUIRED"] = "true"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["AUTH_JWT_SECRET"] = "test-secret-with-sufficient-length-32"
    os.environ["AUTH_JWT_ISSUER"] = "researchops-api"

    get_settings.cache_clear()
    get_auth_config.cache_clear()

    app = create_app()

    run_id_suffix = uuid4().hex[:8]
    email = f"shared-{run_id_suffix}@example.com"

    with TestClient(app) as client:
        first = client.post(
            "/auth/register",
            json={
                "username": f"first-{run_id_suffix}",
                "email": email,
                "password": "password123",
            },
        )
        assert first.status_code == 200

        duplicate = client.post(
            "/auth/register",
            json={
                "username": f"second-{run_id_suffix}",
                "email": email,
                "password": "password123",
            },
        )

        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "Email already exists"
