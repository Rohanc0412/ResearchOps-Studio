from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    prefix = prefix.strip()
    if not prefix or any(c.isspace() for c in prefix):
        raise ValueError("prefix must be a non-empty string without whitespace")
    return f"{prefix}_{uuid.uuid4().hex}"

