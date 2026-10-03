"""core/security.py — password hashing, JWT issue/verify, role hierarchy.

Kept behind this single module so swapping to OAuth2/OIDC later does not touch
business logic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str, kind: str = "access") -> str:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_minutes) if kind == "access" else timedelta(days=s.refresh_token_days)
    payload = {"sub": username, "role": role, "type": kind, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


_REVOKED_JTIS: set[str] = set()


def revoke_token(jti: str) -> None:
    """Revoke a token by its unique identifier (JTI)."""
    _REVOKED_JTIS.add(jti)


def is_token_revoked(jti: str) -> bool:
    """Check if a token has been revoked."""
    return jti in _REVOKED_JTIS


def decode_token(token: str, expected_kind: str = "access") -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})
    if payload.get("type") != expected_kind:
        raise jwt.InvalidTokenError("wrong token type")
    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        raise jwt.InvalidTokenError("token has been revoked")
    return payload


def role_allows(role: str, required: str) -> bool:
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[required]
