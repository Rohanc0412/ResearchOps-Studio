from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from researchops_api.middlewares.auth import get_identity
from researchops_core.auth.config import get_auth_config
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(identity: Identity = Depends(get_identity)) -> dict[str, object]:
    return {"user_id": identity.user_id, "tenant_id": identity.tenant_id, "roles": identity.roles}


@router.get("/auth/jwks-status")
def jwks_status(request: Request, identity: Identity = Depends(get_identity)) -> dict[str, object]:
    try:
        require_roles("admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    runtime = request.app.state.auth_runtime
    cfg = get_auth_config()
    if runtime.jwks_cache is None:
        raise HTTPException(status_code=400, detail="JWKS cache not configured (auth disabled or bypassed)")
    status = runtime.jwks_cache.status()
    return {
        "issuer": str(cfg.oidc_issuer) if cfg.oidc_issuer else None,
        "jwks_uri": status.jwks_uri,
        "cache_age_seconds": status.cache_age_seconds,
        "key_count": status.key_count,
        "last_fetch_ok": status.last_fetch_ok,
    }
