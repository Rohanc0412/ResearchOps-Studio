from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    tenant_id: str
    roles: list[str]
    raw_claims: dict[str, Any]


TENANT_CLAIM_PRIMARY = "https://researchops.ai/tenant_id"
TENANT_CLAIM_FALLBACK = "tenant_id"


def extract_identity(claims: dict[str, Any], *, client_id: str | None = None) -> Identity:
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise ValueError("JWT missing required 'sub'")

    tenant = claims.get(TENANT_CLAIM_PRIMARY) or claims.get(TENANT_CLAIM_FALLBACK)
    if not isinstance(tenant, str) or not tenant.strip():
        raise ValueError("JWT missing required tenant_id claim")

    roles = _extract_roles(claims, client_id=client_id)
    if not roles:
        roles = ["viewer"]
    roles_norm = sorted({r.strip().lower() for r in roles if isinstance(r, str) and r.strip()})
    if not roles_norm:
        roles_norm = ["viewer"]

    return Identity(user_id=sub, tenant_id=tenant, roles=roles_norm, raw_claims=claims)


def _extract_roles(claims: dict[str, Any], *, client_id: str | None) -> list[str]:
    roles = claims.get("roles")
    if isinstance(roles, list):
        return [r for r in roles if isinstance(r, str)]

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        rr = realm_access.get("roles")
        if isinstance(rr, list):
            return [r for r in rr if isinstance(r, str)]

    if client_id:
        resource_access = claims.get("resource_access")
        if isinstance(resource_access, dict):
            client = resource_access.get(client_id)
            if isinstance(client, dict):
                cr = client.get("roles")
                if isinstance(cr, list):
                    return [r for r in cr if isinstance(r, str)]

    return []

