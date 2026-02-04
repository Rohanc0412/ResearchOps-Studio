from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_totp_secret(bytes_len: int = 20) -> str:
    raw = secrets.token_bytes(bytes_len)
    return base64.b32encode(raw).decode("utf-8").strip("=").upper()


def build_otpauth_uri(
    *,
    secret: str,
    account_name: str,
    issuer: str,
    period: int = 30,
    digits: int = 6,
) -> str:
    label = f"{issuer}:{account_name}"
    return (
        "otpauth://totp/"
        f"{quote(label)}?secret={quote(secret)}&issuer={quote(issuer)}"
        f"&period={period}&digits={digits}"
    )


def verify_totp(
    *,
    code: str,
    secret: str,
    period: int = 30,
    digits: int = 6,
    window: int = 1,
    now: float | None = None,
) -> bool:
    if not code or not secret:
        return False
    cleaned = "".join(ch for ch in code if ch.isdigit())
    if len(cleaned) != digits:
        return False
    now = time.time() if now is None else now
    counter = int(now // period)
    for offset in range(-window, window + 1):
        if _totp_at(secret, counter + offset, digits=digits) == cleaned:
            return True
    return False


def _totp_at(secret: str, counter: int, *, digits: int) -> str:
    key = base64.b32decode(_normalize_base32(secret))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def _normalize_base32(secret: str) -> bytes:
    cleaned = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    return (cleaned + padding).encode("utf-8")
