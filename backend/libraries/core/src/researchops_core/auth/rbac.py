from __future__ import annotations

from collections.abc import Callable

from researchops_core.auth.identity import Identity

ROLE_ORDER = ["viewer", "researcher", "admin", "owner"]


def has_role(identity: Identity, role: str) -> bool:
    role = role.strip().lower()
    return role in identity.roles


def require_roles(*allowed: str) -> Callable[[Identity], Identity]:
    allowed_norm = {a.strip().lower() for a in allowed if a.strip()}
    if not allowed_norm:
        raise ValueError("require_roles requires at least one role")

    def _dep(identity: Identity) -> Identity:
        if any(r in identity.roles for r in allowed_norm):
            return identity
        raise PermissionError(f"RBAC forbidden; required one of: {sorted(allowed_norm)}")

    return _dep


def require_tenant(identity: Identity, tenant_id: str) -> Identity:
    if identity.tenant_id != tenant_id:
        raise PermissionError("Cross-tenant access denied")
    return identity

