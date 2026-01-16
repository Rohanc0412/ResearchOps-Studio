from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from researchops_core.auth.config import get_auth_config
from researchops_core.auth.exceptions import (
    AuthAudienceError,
    AuthExpiredError,
    AuthInvalidTokenError,
    AuthIssuerError,
    AuthMissingError,
)
from researchops_core.auth.identity import Identity, extract_identity
from researchops_core.auth.jwks_cache import JWKSCache
from researchops_core.auth.jwt_verify import verify_jwt
from researchops_core.settings import get_settings
from researchops_observability.logging import bind_log_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthRuntime:
    jwks_cache: JWKSCache | None


def init_auth_runtime() -> AuthRuntime:
    settings = get_settings()
    cfg = get_auth_config()
    cfg.validate_for_startup(environment=settings.environment)
    if cfg.auth_required and not cfg.dev_bypass_auth:
        assert cfg.oidc_issuer is not None
        jwks_cache = JWKSCache(
            issuer=str(cfg.oidc_issuer), cache_seconds=cfg.oidc_jwks_cache_seconds
        )
    else:
        jwks_cache = None
    return AuthRuntime(jwks_cache=jwks_cache)


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
        request.state.identity = identity
        bind_log_context(tenant_id_value=identity.tenant_id, run_id_value=None)
        return identity

    if not cfg.auth_required:
        identity = Identity(
            user_id="anonymous",
            tenant_id="00000000-0000-0000-0000-000000000001",
            roles=["viewer"],
            raw_claims={},
        )
        request.state.identity = identity
        bind_log_context(tenant_id_value=identity.tenant_id, run_id_value=None)
        return identity

    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    if runtime.jwks_cache is None:
        raise HTTPException(status_code=500, detail="Auth runtime not configured")

    try:
        claims = verify_jwt(
            token=token,
            issuer=str(cfg.oidc_issuer).rstrip("/"),
            audience=str(cfg.oidc_audience),
            jwks_cache=runtime.jwks_cache,
            clock_skew_seconds=cfg.oidc_clock_skew_seconds,
        )
        identity = extract_identity(claims, client_id=str(cfg.oidc_audience))
    except (AuthMissingError, AuthInvalidTokenError) as e:
        raise HTTPException(status_code=401, detail=str(e) or "Invalid token") from e
    except AuthExpiredError as e:
        raise HTTPException(status_code=401, detail="Token expired") from e
    except (AuthIssuerError, AuthAudienceError) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    request.state.identity = identity
    bind_log_context(tenant_id_value=identity.tenant_id, run_id_value=None)
    logger.info("auth_ok", extra={"user_id": identity.user_id, "tenant_id": identity.tenant_id})
    return identity


IdentityDep = Depends(get_identity)
