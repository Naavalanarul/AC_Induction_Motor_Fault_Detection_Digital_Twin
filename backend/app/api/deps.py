"""api/deps.py — auth/RBAC dependencies enforced on every route."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token, role_allows
from app.db.models import User
from app.db.session import get_db

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    username: str
    role: str


def principal_from_token(token: str, db: Session) -> Principal:
    try:
        payload = decode_token(token, "access")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user disabled or missing")
    return Principal(user.username, user.role.value)


def current_principal(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                      db: Session = Depends(get_db)) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return principal_from_token(creds.credentials, db)


def require(role: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not role_allows(p.role, role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role '{role}'")
        return p

    return dep


def runtime(request: Request):
    return request.app.state.runtime
