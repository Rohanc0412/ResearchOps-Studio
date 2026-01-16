from __future__ import annotations

import pytest

from researchops_core.auth.identity import extract_identity


def test_reject_missing_tenant_id() -> None:
    claims = {"sub": "u1", "iss": "x", "aud": "y", "exp": 1, "iat": 1}
    with pytest.raises(ValueError, match="tenant_id"):
        extract_identity(claims)


def test_role_extraction_roles_list() -> None:
    claims = {
        "sub": "u1",
        "https://researchops.ai/tenant_id": "t1",
        "roles": ["Researcher", "viewer"],
    }
    ident = extract_identity(claims)
    assert ident.roles == ["researcher", "viewer"]


def test_role_extraction_realm_access() -> None:
    claims = {
        "sub": "u1",
        "tenant_id": "t1",
        "realm_access": {"roles": ["Admin"]},
    }
    ident = extract_identity(claims)
    assert ident.roles == ["admin"]


def test_role_extraction_resource_access_client_roles() -> None:
    claims = {
        "sub": "u1",
        "tenant_id": "t1",
        "resource_access": {"my-client": {"roles": ["Owner"]}},
    }
    ident = extract_identity(claims, client_id="my-client")
    assert ident.roles == ["owner"]


def test_default_viewer_when_missing_roles() -> None:
    claims = {"sub": "u1", "tenant_id": "t1"}
    ident = extract_identity(claims)
    assert ident.roles == ["viewer"]

