from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from researchops_core.auth.config import get_auth_config
from researchops_core.auth.exceptions import (
    AuthExpiredError,
    AuthInvalidTokenError,
    AuthIssuerError,
    AuthMissingError,
)
from researchops_core.auth.identity import Identity, extract_identity
from researchops_core.auth.tokens import verify_access_token
from researchops_observability.context import bind
from researchops_core.settings import get_settings



@dataclass(frozen=True, slots=True)
class AuthRuntime:
    enabled: bool


def init_auth_runtime() -> AuthRuntime:
    settings = get_settings()
    cfg = get_auth_config()
    cfg.validate_for_startup(environment=settings.environment)
    enabled = cfg.auth_required and not cfg.dev_bypass_auth
    return AuthRuntime(enabled=enabled)


def get_identity(request: Request) -> Identity:
    cfg = get_auth_config()
    runtime: AuthRuntime = request.app.state.auth_runtime

    if cfg.dev_bypass_auth:
        user_id = request.headers.get("x-dev-user-id", "dev-user")
        tenant_id = request.headers.get("x-dev-tenant-id", "00000000-0000-0000-0000-000000000001")
        roles_raw = request.headers.get("x-dev-roles", "owner")
        roles = [r.strip().lower() for r in roles_raw.split(",") if r.strip()]
        identity = Identity(
            user_id=user_id, tenant_id=tenant_id, roles=roles or ["viewer"], raw_claims={}
        )
        bind(tenant_id=identity.tenant_id)
        request.state.identity = identity
        return identity

    if not cfg.auth_required:
        identity = Identity(
            user_id="anonymous",
            tenant_id="00000000-0000-0000-0000-000000000001",
            roles=["viewer"],
            raw_claims={},
        )
        bind(tenant_id=identity.tenant_id)
        request.state.identity = identity
        return identity

    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    if not runtime.enabled:
        raise HTTPException(status_code=500, detail="Auth runtime not configured")

    try:
        if cfg.auth_jwt_secret is None:
            raise HTTPException(status_code=500, detail="Auth secret not configured")
        claims = verify_access_token(
            token=token,
            secret=cfg.auth_jwt_secret,
            issuer=cfg.auth_jwt_issuer,
            clock_skew_seconds=cfg.auth_clock_skew_seconds,
        )
        identity = extract_identity(claims, client_id=None)
    except (AuthMissingError, AuthInvalidTokenError) as e:
        raise HTTPException(status_code=401, detail=str(e) or "Invalid token") from e
    except AuthExpiredError as e:
        raise HTTPException(status_code=401, detail="Token expired") from e
    except AuthIssuerError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    bind(tenant_id=identity.tenant_id)
    request.state.identity = identity
    return identity


IdentityDep = Depends(get_identity)
