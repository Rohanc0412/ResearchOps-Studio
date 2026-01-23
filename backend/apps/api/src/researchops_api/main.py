from __future__ import annotations

import uvicorn

from researchops_api import create_app
from researchops_core import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.api_host, port=settings.api_port, log_config=None)


if __name__ == "__main__":
    main()

