from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/researchops")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    worker_poll_seconds: float = Field(default=1.0, gt=0.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
