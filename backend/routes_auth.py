"""Account endpoints: /api/auth/*  (see auth.py for the rules)."""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models
import tenancy
from database import get_db
from services import notification_service as tg

logger = logging.getLogger("auth_routes")
router = APIRouter(prefix="/api/auth", tags=["accounts"])


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)
    name: Optional[str] = Field(default=None, max_length=120)
    signup_code: Optional[str] = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=auth.MAX_PASSWORD)


class ProfileIn(BaseModel):
    name: str = Field(default="", max_length=120)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=auth.MAX_PASSWORD)
    new_password: str = Field(max_length=auth.MAX_PASSWORD)


class DeleteIn(BaseModel):
    password: str = Field(max_length=auth.MAX_PASSWORD)


def _me(request: Request, db: Session) -> models.User:
    """The signed-in user's row. Accounts must be on."""
    if not tenancy.auth_enabled():
        raise HTTPException(status_code=400, detail="Accounts are turned off on this server (AUTH_ENABLED=false).")
    uid = auth.current_user_id(request)
    user = db.query(models.User).filter(models.User.id == uid).first() if uid is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def _session(db: Session, user: models.User) -> dict:
    return {"token": auth.make_token(user), "user": auth.public_user(db, user)}


@router.get("/config")
def auth_config(db: Session = Depends(get_db)):
    """What the sign-in page needs to know. Public."""
    enabled = tenancy.auth_enabled()
    return {
        "auth_enabled": enabled,
        "signup_open": auth.signup_open() if enabled else False,
        "signup_code_required": auth.signup_code_required() if enabled else False,
        # The very first account keeps the data that existed before accounts were added.
        "first_account": bool(enabled and db.query(func.count(models.User.id)).scalar() == 0),
    }


@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not tenancy.auth_enabled():
        raise HTTPException(status_code=400, detail="Accounts are turned off on this server (AUTH_ENABLED=false).")
    wait = auth.login_limiter.blocked_for(f"r:{auth.client_ip(request)}")
    if wait > 0:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    try:
        user = auth.create_user(db, payload.email, payload.password, payload.name, payload.signup_code)
    except HTTPException as exc:
        if exc.status_code in (403, 409, 422):
            auth.login_limiter.fail(f"r:{auth.client_ip(request)}")
        raise
    return _session(db, user)


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    if not tenancy.auth_enabled():
        raise HTTPException(status_code=400, detail="Accounts are turned off on this server (AUTH_ENABLED=false).")
    user = auth.authenticate_credentials(db, payload.email, payload.password, auth.client_ip(request))
    return _session(db, user)


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    if not tenancy.auth_enabled():
        return {"auth_enabled": False, "user": None}
    user = _me(request, db)
    return {"auth_enabled": True, "user": auth.public_user(db, user)}


@router.put("/me")
def update_me(payload: ProfileIn, request: Request, db: Session = Depends(get_db)):
    user = _me(request, db)
    user.name = payload.name.strip() or None
    db.commit()
    return {"user": auth.public_user(db, user)}


@router.post("/change-password")
def change_password(payload: PasswordIn, request: Request, db: Session = Depends(get_db)):
    user = _me(request, db)
    auth.change_password(db, user, payload.current_password, payload.new_password)
    return {"message": "Password changed. Other devices were signed out.", **_session(db, user)}


@router.post("/logout-all")
def logout_all(request: Request, db: Session = Depends(get_db)):
    user = _me(request, db)
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    return {"message": "Signed out everywhere else.", **_session(db, user)}


@router.post("/telegram/link")
def telegram_link(request: Request, db: Session = Depends(get_db)):
    """A one-time code: send `/start <code>` to the bot from the chat that should receive this user's alerts."""
    user = _me(request, db)
    if not (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
        raise HTTPException(status_code=503, detail="Telegram is not set up on this server (no bot token).")
    code, seconds = auth.new_telegram_link_code(db, user)
    username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@") or None
    if username is None:
        try:
            username = (tg.call_telegram("getMe", {}) or {}).get("username")
        except tg.TelegramNotificationError as exc:
            logger.warning(f"Could not read the bot username: {exc}")
    return {
        "code": code, "expires_in": seconds, "bot_username": username,
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
        "instructions": f"Open the bot in Telegram and send /start {code} (valid for {seconds // 60} minutes).",
    }


@router.delete("/telegram")
def telegram_unlink(request: Request, db: Session = Depends(get_db)):
    user = _me(request, db)
    user.telegram_chat_id, user.telegram_link_code, user.telegram_link_expires = None, None, None
    db.commit()
    return {"user": auth.public_user(db, user)}


@router.delete("/account")
def delete_account(payload: DeleteIn, request: Request, db: Session = Depends(get_db)):
    """Delete the account and every job, resume, setting and application that belongs to it."""
    user = _me(request, db)
    if not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="The password is wrong.")
    counts = auth.delete_account(db, user)
    return {"message": "Your account and data were deleted.", "deleted": counts}
