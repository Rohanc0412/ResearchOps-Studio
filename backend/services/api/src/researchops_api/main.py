from __future__ import annotations

import uvicorn
import logging
from dotenv import find_dotenv, load_dotenv

from researchops_api import create_app
from researchops_core import SERVICE_API, get_settings
from researchops_observability import setup_logging


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
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

