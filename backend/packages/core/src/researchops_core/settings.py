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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file() or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="local")
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/researchops")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    worker_poll_seconds: float = Field(default=1.0, gt=0.0)
    llm_provider: str | None = Field(default=None)
    hosted_llm_base_url: str | None = Field(default=None)
    hosted_llm_api_key: str | None = Field(default=None)
    hosted_llm_model: str | None = Field(default=None)
    llm_outline_debug_simple_prompt: bool | None = Field(default=None)
    retriever_max_sources: int | None = Field(default=None)
    retriever_max_queries: int | None = Field(default=None)
    retriever_min_queries: int | None = Field(default=None)
    retriever_max_per_query: int | None = Field(default=None)
    retriever_max_keyword_results: int | None = Field(default=None)
    retriever_max_vector_results: int | None = Field(default=None)
    retriever_include_embeddings: bool | None = Field(default=None)
    retriever_vector_search: bool | None = Field(default=None)
    retriever_max_snippets_per_source: int | None = Field(default=None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
