from __future__ import annotations

import contextlib

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, bearer, current_principal, require
from app.api.schemas import LoginIn, RefreshIn, TokenOut, UserIn, UserOut
from app.config import get_settings
from app.core.ratelimit import rate_limit
from app.core.security import create_token, decode_token, hash_password, revoke_token, verify_password
from app.db.models import RoleEnum, User
from app.db.session import get_db

router = APIRouter(tags=["auth"])
_login_limit = rate_limit("login", lambda: get_settings().login_rate_per_min)


def _tokens(user: User) -> TokenOut:
    return TokenOut(access_token=create_token(user.username, user.role.value, "access"),
                    refresh_token=create_token(user.username, user.role.value, "refresh"),
                    role=user.role.value, username=user.username)


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(_login_limit)])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return _tokens(user)


@router.post("/auth/refresh", response_model=TokenOut, dependencies=[Depends(_login_limit)])
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from exc
    # Revoke old refresh token to enforce rotation
    if "jti" in payload:
        revoke_token(payload["jti"])
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user disabled or missing")
    return _tokens(user)


@router.post("/auth/logout", status_code=200)
def logout(body: RefreshIn | None = None, creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """Revokes access and/or refresh tokens upon user logout."""
    if creds is not None:
        with contextlib.suppress(Exception):
            payload = decode_token(creds.credentials, "access")
            if "jti" in payload:
                revoke_token(payload["jti"])
    if body and body.refresh_token:
        with contextlib.suppress(Exception):
            payload = decode_token(body.refresh_token, "refresh")
            if "jti" in payload:
                revoke_token(payload["jti"])
    return {"message": "logged out successfully"}


@router.get("/auth/me")
def me(p: Principal = Depends(current_principal)):
    return {"username": p.username, "role": p.role}


@router.get("/users", response_model=list[UserOut])
def list_users(_: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, _: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "username exists")
    user = User(username=body.username, password_hash=hash_password(body.password), role=RoleEnum(body.role))
    db.add(user)
    db.commit()
    return user
