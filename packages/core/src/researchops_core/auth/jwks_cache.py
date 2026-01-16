from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class JWKSStatus:
    issuer: str
    jwks_uri: str
    cache_age_seconds: int | None
    key_count: int
    last_fetch_ok: bool


class JWKSCache:
    def __init__(self, *, issuer: str, cache_seconds: int = 300, http_client: httpx.Client | None = None) -> None:
        self._issuer = issuer.rstrip("/")
        self._cache_seconds = cache_seconds
        self._http = http_client or httpx.Client(timeout=5.0)

        self._lock = threading.Lock()
        self._jwks_uri: str | None = None
        self._keys: list[dict[str, Any]] | None = None
        self._fetched_at: float | None = None
        self._last_fetch_ok = False

    def jwks_uri(self) -> str:
        if self._jwks_uri is None:
            self._jwks_uri = self._discover_jwks_uri()
        return self._jwks_uri

    def get_jwks(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if self._keys is not None and self._fetched_at is not None:
                if now - self._fetched_at < self._cache_seconds:
                    return {"keys": self._keys}

            try:
                jwks = self._fetch_jwks()
                self._keys = jwks.get("keys", [])
                self._fetched_at = now
                self._last_fetch_ok = True
                return {"keys": self._keys}
            except Exception:
                self._last_fetch_ok = False
                raise

    def status(self) -> JWKSStatus:
        age: int | None = None
        if self._fetched_at is not None:
            age = int(time.time() - self._fetched_at)
        return JWKSStatus(
            issuer=self._issuer,
            jwks_uri=self.jwks_uri(),
            cache_age_seconds=age,
            key_count=len(self._keys or []),
            last_fetch_ok=self._last_fetch_ok,
        )

    def _discover_jwks_uri(self) -> str:
        discovery = f"{self._issuer}/.well-known/openid-configuration"
        resp = self._http.get(discovery)
        resp.raise_for_status()
        data = resp.json()
        jwks_uri = data.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise ValueError("OIDC discovery missing jwks_uri")
        return jwks_uri

    def _fetch_jwks(self) -> dict[str, Any]:
        resp = self._http.get(self.jwks_uri())
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "keys" not in data:
            raise ValueError("Invalid JWKS payload")
        return data

