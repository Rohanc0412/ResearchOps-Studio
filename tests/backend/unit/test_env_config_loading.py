from __future__ import annotations

import os
from pathlib import Path

from core.auth.config import AuthConfig
from core.env import load_root_env, resolve_root_env_file
from core.settings import Settings


def test_resolve_root_env_file_ignores_service_local_env(tmp_path: Path):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "backend"
    frontend_dir = repo_root / "frontend" / "dashboard"
    probe = backend_dir / "services" / "api" / "main.py"

    (repo_root / ".git").mkdir(parents=True)
    probe.parent.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)

    root_env = repo_root / ".env"
    root_env.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    (backend_dir / ".env").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    (frontend_dir / ".env").write_text("VITE_API_BASE_URL=http://bad\n", encoding="utf-8")

    assert resolve_root_env_file(probe) == root_env.resolve()

    root_env.unlink()
    assert resolve_root_env_file(probe) is None


def test_load_root_env_reads_only_repo_root(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "backend"
    frontend_dir = repo_root / "frontend" / "dashboard"
    probe = backend_dir / "services" / "workers" / "main.py"

    (repo_root / ".git").mkdir(parents=True)
    probe.parent.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)

    (repo_root / ".env").write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")
    (backend_dir / ".env").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    (frontend_dir / ".env").write_text("VITE_API_BASE_URL=http://bad\n", encoding="utf-8")

    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("VITE_API_BASE_URL", raising=False)

    load_root_env(probe)

    assert os.environ["LOG_LEVEL"] == "WARNING"
    assert "VITE_API_BASE_URL" not in os.environ


def test_settings_and_auth_process_env_override_root_env(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ENVIRONMENT=file-env",
                "AUTH_REQUIRED=true",
                "AUTH_JWT_SECRET=file-secret",
                "AUTH_JWT_ISSUER=file-issuer",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ENVIRONMENT", "shell-env")
    monkeypatch.setenv("AUTH_JWT_SECRET", "shell-secret")

    settings = Settings(_env_file=str(env_file))
    auth = AuthConfig(_env_file=str(env_file))

    assert settings.environment == "shell-env"
    assert auth.auth_jwt_secret == "shell-secret"
    assert auth.auth_jwt_issuer == "file-issuer"
