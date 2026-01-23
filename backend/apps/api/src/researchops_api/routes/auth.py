from __future__ import annotations

from fastapi import APIRouter, Depends

from researchops_api.middlewares.auth import get_identity
from researchops_core.auth.identity import Identity

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(identity: Identity = Depends(get_identity)) -> dict[str, object]:
    return {"user_id": identity.user_id, "tenant_id": identity.tenant_id, "roles": identity.roles}


