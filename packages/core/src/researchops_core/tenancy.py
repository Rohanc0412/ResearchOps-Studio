from __future__ import annotations

from uuid import UUID, uuid5


_TENANT_NAMESPACE = UUID("6d7f9a0e-84c4-4c8e-9a5b-4d7b2d3c6a10")


def tenant_uuid(tenant_id: str) -> UUID:
    """
    Converts an auth-layer tenant_id (string) into a stable UUID for DB storage.

    - If tenant_id is already a UUID string, it is parsed as-is.
    - Otherwise, we deterministically derive a UUIDv5 from a fixed namespace.
    """
    try:
        return UUID(tenant_id)
    except ValueError:
        return uuid5(_TENANT_NAMESPACE, tenant_id)

