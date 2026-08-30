"""
Authentication utilities: password hashing and JWT token creation/verification.

SECRET_KEY MUST be set via environment variable in production - the fallback
here is only for local development. If this leaks, anyone can forge tokens
and impersonate any user.
"""

import os
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # tokens stay valid for a week before re-login is required


def hash_password(plain_password: str) -> str:
    """Hashes a password for storage. Never store plain passwords."""
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    """Creates a signed token proving 'this request really is from user_id'.
    The frontend/watcher stores this after login and sends it on every request."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Verifies a token's signature and expiry, returns the user_id it proves,
    or None if the token is invalid/expired/tampered with."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
