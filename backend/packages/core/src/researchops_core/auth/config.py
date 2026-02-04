from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str | None:
    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        candidate = base / ".env"
        if candidate.exists():
            return str(candidate)
    for base in Path(__file__).resolve().parents:
        candidate = base / ".env"
        if candidate.exists():
            return str(candidate)
    return None


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file() or ".env", env_file_encoding="utf-8", extra="ignore"
    )

    auth_required: bool = Field(default=True, validation_alias="AUTH_REQUIRED")
    dev_bypass_auth: bool = Field(default=False, validation_alias="DEV_BYPASS_AUTH")

    auth_jwt_secret: str | None = Field(default=None, validation_alias="AUTH_JWT_SECRET")
    auth_jwt_issuer: str = Field(default="researchops-api", validation_alias="AUTH_JWT_ISSUER")
    auth_access_token_minutes: int = Field(
        default=30, ge=1, validation_alias="AUTH_ACCESS_TOKEN_MINUTES"
    )
    auth_refresh_token_days: int = Field(
        default=14, ge=1, validation_alias="AUTH_REFRESH_TOKEN_DAYS"
    )
    auth_refresh_cookie_name: str = Field(
        default="researchops_refresh", validation_alias="AUTH_REFRESH_COOKIE_NAME"
    )
    auth_refresh_cookie_secure: bool | None = Field(
        default=None, validation_alias="AUTH_REFRESH_COOKIE_SECURE"
    )
    auth_refresh_cookie_samesite: str = Field(
        default="lax", validation_alias="AUTH_REFRESH_COOKIE_SAMESITE"
    )
    auth_refresh_token_secret: str | None = Field(
        default=None, validation_alias="AUTH_REFRESH_TOKEN_SECRET"
    )
    auth_allow_register: bool = Field(default=True, validation_alias="AUTH_ALLOW_REGISTER")
    auth_clock_skew_seconds: int = Field(
        default=60, ge=0, validation_alias="AUTH_CLOCK_SKEW_SECONDS"
    )
    auth_mfa_challenge_minutes: int = Field(
        default=5, ge=1, validation_alias="AUTH_MFA_CHALLENGE_MINUTES"
    )
    auth_mfa_totp_issuer: str = Field(
        default="ResearchOps Studio", validation_alias="AUTH_MFA_TOTP_ISSUER"
    )
    auth_mfa_totp_period_seconds: int = Field(
        default=30, ge=15, validation_alias="AUTH_MFA_TOTP_PERIOD_SECONDS"
    )
    auth_mfa_totp_digits: int = Field(
        default=6, ge=6, le=8, validation_alias="AUTH_MFA_TOTP_DIGITS"
    )
    auth_mfa_totp_window: int = Field(
        default=1, ge=0, le=5, validation_alias="AUTH_MFA_TOTP_WINDOW"
    )

    auth_google_client_id: str | None = Field(
        default=None, validation_alias="AUTH_GOOGLE_CLIENT_ID"
    )
    auth_google_issuer: str = Field(
        default="https://accounts.google.com", validation_alias="AUTH_GOOGLE_ISSUER"
    )
    auth_google_allow_link_existing: bool = Field(
        default=True, validation_alias="AUTH_GOOGLE_ALLOW_LINK_EXISTING"
    )
    auth_google_jwks_cache_seconds: int = Field(
        default=300, ge=30, validation_alias="AUTH_GOOGLE_JWKS_CACHE_SECONDS"
    )

    def validate_for_startup(self, *, environment: str) -> None:
        if self.dev_bypass_auth and environment != "local":
            raise ValueError("DEV_BYPASS_AUTH is only allowed in environment=local")
        if self.auth_required and not self.dev_bypass_auth:
            if self.auth_jwt_secret is None or not self.auth_jwt_secret.strip():
                raise ValueError("AUTH_JWT_SECRET is required when AUTH_REQUIRED=true")


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    return AuthConfig()

