from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    auth_required: bool = Field(default=True, validation_alias="AUTH_REQUIRED")
    dev_bypass_auth: bool = Field(default=False, validation_alias="DEV_BYPASS_AUTH")

    oidc_issuer: AnyHttpUrl | None = Field(default=None, validation_alias="OIDC_ISSUER")
    oidc_audience: str | None = Field(default=None, validation_alias="OIDC_AUDIENCE")
    oidc_jwks_cache_seconds: int = Field(default=300, ge=1, validation_alias="OIDC_JWKS_CACHE_SECONDS")
    oidc_clock_skew_seconds: int = Field(default=60, ge=0, validation_alias="OIDC_CLOCK_SKEW_SECONDS")

    def validate_for_startup(self, *, environment: str) -> None:
        if self.dev_bypass_auth and environment != "local":
            raise ValueError("DEV_BYPASS_AUTH is only allowed in environment=local")
        if self.auth_required and not self.dev_bypass_auth:
            if self.oidc_issuer is None:
                raise ValueError("OIDC_ISSUER is required when AUTH_REQUIRED=true")
            if self.oidc_audience is None or not self.oidc_audience.strip():
                raise ValueError("OIDC_AUDIENCE is required when AUTH_REQUIRED=true")


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    return AuthConfig()

