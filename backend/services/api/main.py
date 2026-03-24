from __future__ import annotations

import logging

import uvicorn
from app import create_app
from core import SERVICE_API, get_settings
from core.env import resolve_env_files
from dotenv import load_dotenv
from observability import setup_logging


def main() -> None:
    for env_file in resolve_env_files():
        load_dotenv(env_file, override=False)
    settings = get_settings()
    setup_logging(SERVICE_API)
    logging.getLogger(__name__).info(
        "API starting",
        extra={
            "event": "api.startup",
            "environment": settings.environment,
            "host": settings.api_host,
            "port": settings.api_port,
        },
    )
    uvicorn.run(create_app(), host=settings.api_host, port=settings.api_port, log_config=None)


if __name__ == "__main__":
    main()

