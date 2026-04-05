from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.env import resolve_root_env_file

_ROOT_ENV_FILE = resolve_root_env_file()


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV_FILE) if _ROOT_ENV_FILE is not None else None,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
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
    auth_password_reset_minutes: int = Field(
        default=30, ge=5, validation_alias="AUTH_PASSWORD_RESET_MINUTES"
    )
    auth_password_reset_secret: str | None = Field(
        default=None, validation_alias="AUTH_PASSWORD_RESET_SECRET"
    )

    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, validation_alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, validation_alias="SMTP_PASSWORD")
    smtp_starttls: bool = Field(default=True, validation_alias="SMTP_STARTTLS")
    smtp_from_name: str = Field(default="noreply researchstudio", validation_alias="SMTP_FROM_NAME")
    smtp_from_email: str | None = Field(default=None, validation_alias="SMTP_FROM_EMAIL")

    def validate_for_startup(self, *, environment: str) -> None:
        if self.dev_bypass_auth and environment != "local":
            raise ValueError("DEV_BYPASS_AUTH is only allowed in environment=local")
        if self.auth_required and not self.dev_bypass_auth:
            if self.auth_jwt_secret is None or not self.auth_jwt_secret.strip():
                raise ValueError("AUTH_JWT_SECRET is required when AUTH_REQUIRED=true")


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    return AuthConfig()

