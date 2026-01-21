from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from researchops_api import create_app
from researchops_core.auth.config import get_auth_config
from researchops_core.settings import get_settings


def _rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _jwk_from_public(public_key, *, kid: str) -> dict:
    from jwt.algorithms import RSAAlgorithm

    jwk = RSAAlgorithm.to_jwk(public_key)
    import json

    d = json.loads(jwk)
    d["kid"] = kid
    d["use"] = "sig"
    d["alg"] = "RS256"
    return d


def _oidc_mock_client(*, issuer: str, jwks: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200, json={"issuer": issuer.rstrip("/"), "jwks_uri": f"{issuer.rstrip('/')}/jwks"}
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json=jwks)
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url=issuer.rstrip("/"))


def _mint_token(
    *, private_key, issuer: str, audience: str, tenant_id: str, roles: list[str], kid: str
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_123",
        "iss": issuer.rstrip("/"),
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "https://researchops.ai/tenant_id": tenant_id,
        "roles": roles,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def test_auth_rbac_and_tenant_isolation_end_to_end(tmp_path) -> None:
    db_path = tmp_path / "e2e.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["LOG_LEVEL"] = "INFO"
    os.environ["WORKER_POLL_SECONDS"] = "0.01"

    os.environ["AUTH_REQUIRED"] = "true"
    os.environ["DEV_BYPASS_AUTH"] = "false"
    os.environ["OIDC_AUDIENCE"] = "researchops-api"
    os.environ["OIDC_ISSUER"] = "http://issuer.test"
    os.environ["OIDC_JWKS_CACHE_SECONDS"] = "300"
    os.environ["OIDC_CLOCK_SKEW_SECONDS"] = "60"

    get_settings.cache_clear()
    get_auth_config.cache_clear()

    private_key, public_key = _rsa_keypair()
    kid = "kid1"
    jwks = {"keys": [_jwk_from_public(public_key, kid=kid)]}

    oidc_client = _oidc_mock_client(issuer=os.environ["OIDC_ISSUER"], jwks=jwks)

    app = create_app()

    with TestClient(app) as client:
        # Patch the internal http client used by JWKS cache to use the ASGI mock.
        app.state.auth_runtime.jwks_cache._http = oidc_client  # type: ignore[attr-defined]

        # Public endpoint works without token
        assert client.get("/health").status_code == 200

        # Protected endpoint blocks without token
        assert client.get("/me").status_code == 401

        token_a = _mint_token(
            private_key=private_key,
            issuer=os.environ["OIDC_ISSUER"],
            audience=os.environ["OIDC_AUDIENCE"],
            tenant_id="00000000-0000-0000-0000-0000000000aa",
            roles=["researcher"],
            kid=kid,
        )
        headers_a = {"Authorization": f"Bearer {token_a}"}

        me = client.get("/me", headers=headers_a).json()
        assert me["tenant_id"] == "00000000-0000-0000-0000-0000000000aa"
        assert "researcher" in me["roles"]

        project = client.post("/projects", headers=headers_a, json={"name": "RBAC Project"}).json()
        project_id = project["id"]
        run = client.post(
            f"/projects/{project_id}/runs",
            headers=headers_a,
            json={"prompt": "Summarize LLMs", "output_type": "report"},
        ).json()
        run_id = run.get("id") or run.get("run_id")
        assert run_id is not None

        run_state = client.get(f"/runs/{run_id}", headers=headers_a).json()
        assert run_state["status"] in {"created", "queued", "running"}

        # Cross-tenant access is blocked (404, because tenant-scoped query)
        token_b = _mint_token(
            private_key=private_key,
            issuer=os.environ["OIDC_ISSUER"],
            audience=os.environ["OIDC_AUDIENCE"],
            tenant_id="00000000-0000-0000-0000-0000000000bb",
            roles=["viewer"],
            kid=kid,
        )
        headers_b = {"Authorization": f"Bearer {token_b}"}
        assert client.get(f"/runs/{run_id}", headers=headers_b).status_code == 404
