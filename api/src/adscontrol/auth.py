"""The household PIN. Hash and lockout live in the database, so a restart resets neither."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COOKIE_NAME = "control_session"
SESSION_DAYS = 90
MAX_ATTEMPTS = 5
LOCKOUT_BASE_S = 60
LOCKOUT_MAX_S = 3600
_PIN_FORMAT = re.compile(r"\d{6,12}")


@dataclass(frozen=True)
class AuthRow:
    pin_hash: bytes
    pin_salt: bytes
    signing_key: bytes
    generation: int
    failures: int
    locked_until: datetime | None


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1)


async def load(session: AsyncSession) -> AuthRow | None:
    row = (
        await session.execute(
            text(
                "SELECT pin_hash, pin_salt, signing_key, generation, failures, locked_until FROM auth_settings"
            )
        )
    ).first()
    return AuthRow(**row._mapping) if row else None


async def set_pin(session: AsyncSession, pin: str) -> None:
    """Sets or changes the PIN. Moving the generation on signs every device out."""
    if not _PIN_FORMAT.fullmatch(pin):
        raise ValueError("the PIN must be 6 to 12 digits")
    salt = secrets.token_bytes(16)
    await session.execute(
        text(
            """
            INSERT INTO auth_settings (pin_hash, pin_salt, signing_key, generation)
            VALUES (:hash, :salt, :key, 1)
            ON CONFLICT (id) DO UPDATE SET pin_hash = :hash, pin_salt = :salt,
                generation = auth_settings.generation + 1, failures = 0, locked_until = NULL
            """
        ),
        {"hash": _hash(pin, salt), "salt": salt, "key": secrets.token_bytes(32)},
    )


def _signature(key: bytes, generation: int, expires: int) -> str:
    return hmac.new(key, f"{generation}.{expires}".encode(), hashlib.sha256).hexdigest()


def make_session_value(row: AuthRow, now: datetime) -> str:
    expires = int((now + timedelta(days=SESSION_DAYS)).timestamp())
    return f"{row.generation}.{expires}.{_signature(row.signing_key, row.generation, expires)}"


def session_is_valid(row: AuthRow, value: str | None, now: datetime) -> bool:
    try:
        generation, expires, signature = (value or "").split(".")
        generation_n, expires_n = int(generation), int(expires)
    except ValueError:
        return False
    expected = _signature(row.signing_key, generation_n, expires_n)
    return (
        hmac.compare_digest(signature, expected)
        and generation_n == row.generation
        and now.timestamp() < expires_n
    )


def pin_matches(row: AuthRow, pin: str) -> bool:
    return hmac.compare_digest(_hash(pin, row.pin_salt), row.pin_hash)


def lockout_seconds(failures: int) -> int:
    """Nothing until MAX_ATTEMPTS, then 60 s doubling with each further failure, up to an hour."""
    if failures < MAX_ATTEMPTS:
        return 0
    return min(LOCKOUT_BASE_S * 2 ** (failures - MAX_ATTEMPTS), LOCKOUT_MAX_S)


def is_secure(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or request.app.state.settings.allow_insecure_pin
    )


async def require_pin(request: Request) -> None:
    """Route dependency: cameras and thermostat changes sit behind this."""
    if not is_secure(request):
        raise HTTPException(status_code=400, detail="use the HTTPS address")
    now: datetime = request.app.state.clock().astimezone(timezone.utc)
    async with request.app.state.sessions() as session:
        row = await load(session)
    if row is None or not session_is_valid(row, request.cookies.get(COOKIE_NAME), now):
        raise HTTPException(status_code=401, detail="PIN required")
