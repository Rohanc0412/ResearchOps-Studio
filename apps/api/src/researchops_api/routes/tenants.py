from __future__ import annotations

from fastapi import APIRouter, Depends

from researchops_api.middlewares.auth import get_identity
from researchops_core.auth.identity import Identity

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/current")
def current(identity: Identity = Depends(get_identity)) -> dict[str, str]:
    return {"tenant_id": identity.tenant_id}
