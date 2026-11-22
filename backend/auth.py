"""
Accounts: password hashing, session tokens, the sign-in check for every request, and per-user helpers.

Settings (environment):
  AUTH_ENABLED        default true. false = single-user local mode with no sign-in (the old behaviour).
  AUTH_SECRET         signs session tokens. Set a long random value in production; without it a secret is generated
                      and stored in backend/.auth_secret (fine for local use, but lost on hosts with a temporary disk).
  AUTH_TOKEN_DAYS     how long a sign-in lasts (default 7).
  ALLOW_SIGNUP        default true. false = nobody can create new accounts.
  SIGNUP_CODE         when set, registering also needs this code (an invite code for a shared deployment).
  OWNER_EMAIL         the account that inherits the data that existed before accounts (and may send real e-mails
                      through the server's SMTP account). Default: the first account created.

Security notes
  * Passwords are stored as salted scrypt hashes, compared in constant time; login attempts are rate limited.
  * Tokens are HS256 JWTs; changing the password (or "sign out everywhere") invalidates all older tokens.
  * Every query on user data is filtered to the signed-in user by tenancy.py, whatever the endpoint does.
"""
import base64
import datetime
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

import jwt
from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import tenancy
from database import SessionLocal

logger = logging.getLogger("auth")

BACKEND_DIR = Path(__file__).resolve().parent
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD, MAX_PASSWORD = 8, 128
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
LINK_CODE_MINUTES = 15

# Endpoints that need no sign-in. Everything else under /api requires a valid token when accounts are on.
PUBLIC = {
    ("GET", "/"), ("GET", "/api/health"), ("GET", "/api/auth/config"),
    ("POST", "/api/auth/login"), ("POST", "/api/auth/register"),
    ("POST", "/api/telegram/webhook"),  # checked with its own secret header
    # Legacy ingestion endpoints (old Make.com setup) are protected by X-API-Key and act on the owner account.
    ("POST", "/api/jobs"), ("GET", "/api/make/context"), ("GET", "/api/make/resume"),
}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def signup_open() -> bool:
    return _env_bool("ALLOW_SIGNUP", True)


def signup_code_required() -> bool:
    return bool((os.getenv("SIGNUP_CODE") or "").strip())


def token_days() -> float:
    try:
        return max(0.01, float(os.getenv("AUTH_TOKEN_DAYS", "7")))
    except ValueError:
        return 7.0


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = None


def _burn_time(password: str) -> None:
    """Spend the same time as a real check, so an unknown e-mail cannot be told apart by timing."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password")
    verify_password(password, _DUMMY_HASH)


def validate_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not EMAIL_RE.match(cleaned) or len(cleaned) > 254:
        raise HTTPException(status_code=422, detail="Enter a valid e-mail address.")
    return cleaned


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"The password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise HTTPException(status_code=422, detail=f"The password can be at most {MAX_PASSWORD} characters.")
    return password


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_secret_cache: Optional[str] = None
_secret_lock = threading.Lock()


def _secret() -> str:
    global _secret_cache
    env = (os.getenv("AUTH_SECRET") or "").strip()
    if env:
        return env
    with _secret_lock:
        if _secret_cache:
            return _secret_cache
        path = BACKEND_DIR / ".auth_secret"
        try:
            if path.is_file():
                _secret_cache = path.read_text(encoding="utf-8").strip()
        except OSError:
            _secret_cache = None
        if not _secret_cache:
            _secret_cache = secrets.token_urlsafe(48)
            try:
                path.write_text(_secret_cache, encoding="utf-8")
            except OSError:
                pass
            logger.warning("AUTH_SECRET is not set: using a generated secret (backend/.auth_secret). Set AUTH_SECRET "
                           "in production, otherwise everyone is signed out when the server's disk is reset.")
        return _secret_cache


def make_token(user: models.User) -> str:
    now = int(time.time())
    payload = {"sub": str(user.id), "ver": int(user.token_version or 0), "iat": now,
               "exp": now + int(token_days() * 86400)}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def read_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub", "iat"]})
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Login rate limit (in memory, per e-mail and per address)
# ---------------------------------------------------------------------------
class LoginLimiter:
    def __init__(self, max_failures: int = 8, window_seconds: int = 600):
        self.max_failures, self.window = max_failures, window_seconds
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        kept = [t for t in self._fails.get(key, []) if t > cutoff]
        if kept:
            self._fails[key] = kept
        else:
            self._fails.pop(key, None)
        return kept

    def blocked_for(self, *keys: str) -> float:
        with self._lock:
            worst = 0.0
            for key in keys:
                recent = self._recent(key)
                if len(recent) >= self.max_failures:
                    worst = max(worst, self.window - (time.monotonic() - recent[0]))
            return worst

    def fail(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._fails.setdefault(key, []).append(time.monotonic())

    def clear(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._fails.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


login_limiter = LoginLimiter()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def public_user(db: Session, user: models.User) -> dict:
    return {
        "id": user.id, "email": user.email, "name": user.name or "",
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "telegram_linked": bool(user.telegram_chat_id),
        "is_owner": owner_user_id(db) == user.id,
    }


def owner_user_id(db: Session) -> Optional[int]:
    """The account that owns pre-account data: OWNER_EMAIL if set, else the first account. None before any account."""
    if not tenancy.auth_enabled():
        return None
    email = (os.getenv("OWNER_EMAIL") or "").strip().lower()
    if email:
        row = db.query(models.User.id).filter(models.User.email == email).first()
        return row[0] if row else None
    return db.query(func.min(models.User.id)).scalar()


def claim_legacy_data(db: Session, user_id: int) -> int:
    """Give every row that has no owner (data from before accounts) to this user. Returns the rows moved."""
    tenancy.system_session(db)
    moved = 0
    for model in tenancy.TENANT_MODELS:
        moved += db.query(model).filter(model.user_id.is_(None)).update({"user_id": user_id}, synchronize_session=False)
    db.commit()
    return moved


def create_user(db: Session, email: str, password: str, name: Optional[str] = None,
                signup_code: Optional[str] = None) -> models.User:
    if not signup_open():
        raise HTTPException(status_code=403, detail="Sign-up is closed on this server.")
    required = (os.getenv("SIGNUP_CODE") or "").strip()
    if required and not hmac.compare_digest((signup_code or "").strip().encode(), required.encode()):
        raise HTTPException(status_code=403, detail="That invite code is not valid.")
    email = validate_email(email)
    validate_password(password)
    clean_name = (name or "").strip()[:120] or None
    if db.query(models.User.id).filter(models.User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this e-mail already exists.")
    owner_email = (os.getenv("OWNER_EMAIL") or "").strip().lower()
    first = db.query(func.count(models.User.id)).scalar() == 0
    takes_legacy = (email == owner_email) if owner_email else first
    user = models.User(email=email, password_hash=hash_password(password), name=clean_name, created_at=_utcnow())
    db.add(user)
    try:
        db.commit()
    except Exception:  # two sign-ups with the same e-mail at the same moment
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this e-mail already exists.")
    db.refresh(user)
    if takes_legacy:
        moved = claim_legacy_data(db, user.id)
        if moved:
            logger.info(f"Account {user.id} took over {moved} pre-account row(s).")
    return user


def authenticate_credentials(db: Session, email: str, password: str, client_ip: str = "") -> models.User:
    email_key, ip_key = f"e:{(email or '').strip().lower()}", f"i:{client_ip}"
    wait = login_limiter.blocked_for(email_key, ip_key)
    if wait > 0:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {int(wait // 60) + 1} minute(s).",
                            headers={"Retry-After": str(int(wait) + 1)})
    user = db.query(models.User).filter(models.User.email == (email or "").strip().lower()).first()
    if user is None:
        _burn_time(password or "")
        login_limiter.fail(email_key, ip_key)
        raise HTTPException(status_code=401, detail="Wrong e-mail or password.")
    if not verify_password(password or "", user.password_hash):
        login_limiter.fail(email_key, ip_key)
        raise HTTPException(status_code=401, detail="Wrong e-mail or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    login_limiter.clear(email_key)
    user.last_login_at = _utcnow()
    db.commit()
    return user


def change_password(db: Session, user: models.User, current: str, new: str) -> None:
    if not verify_password(current or "", user.password_hash):
        raise HTTPException(status_code=401, detail="The current password is wrong.")
    validate_password(new)
    user.password_hash = hash_password(new)
    user.token_version = int(user.token_version or 0) + 1   # signs every other device out
    db.commit()


def delete_account(db: Session, user: models.User) -> dict:
    """Remove the user and all of their data (rows and files). Irreversible."""
    uid = user.id
    tenancy.system_session(db)
    files = [r.file_path for r in db.query(models.Resume).filter(models.Resume.user_id == uid).all() if r.file_path]
    for t in db.query(models.TailoredResume).filter(models.TailoredResume.user_id == uid).all():
        files.extend(p for p in (t.pdf_path, t.docx_path) if p)
    counts = {}
    for model in tenancy.TENANT_MODELS:
        counts[model.__tablename__] = db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)
    db.query(models.User).filter(models.User.id == uid).delete(synchronize_session=False)
    db.commit()
    removed = 0
    for path in files:
        try:
            Path(path).unlink()
            removed += 1
        except OSError:
            pass
    counts["files_removed"] = removed
    return counts


# ---------------------------------------------------------------------------
# The sign-in check run before every request
# ---------------------------------------------------------------------------
def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _load_user(user_id: int, version: int) -> Optional[dict]:
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user is None or not user.is_active or int(user.token_version or 0) != version:
            return None
        return {"id": user.id, "email": user.email, "name": user.name or ""}
    finally:
        db.close()


async def authenticate(request: Request) -> None:
    """App-wide dependency: identifies the user, makes get_db scope its session, and keys the per-user state."""
    if request.method == "OPTIONS" or (request.method, request.url.path) in PUBLIC:
        return
    if not tenancy.auth_enabled():
        request.state.user, request.state.tenant, request.state.tenant_set = None, None, True
        tenancy.set_current_user(None)
        return
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    claims = read_token(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
    user = None
    if claims:
        try:
            user = await run_in_threadpool(_load_user, int(claims["sub"]), int(claims.get("ver", 0)))
        except (TypeError, ValueError):
            user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.", headers={"WWW-Authenticate": "Bearer"})
    request.state.user, request.state.tenant, request.state.tenant_set = user, user["id"], True
    tenancy.set_current_user(user["id"])


def current_user(request: Request) -> Optional[dict]:
    """The signed-in user as a small dict (None in single-user mode). Use as a FastAPI dependency."""
    return getattr(request.state, "user", None)


def current_user_id(request: Request) -> Optional[int]:
    user = current_user(request)
    return user["id"] if user else None


# ---------------------------------------------------------------------------
# Telegram: which chat belongs to which user
# ---------------------------------------------------------------------------
def env_chat_id() -> Optional[str]:
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None


def telegram_chat_for(db: Session) -> Optional[str]:
    """Where this session's user gets alerts. Single-user mode and the owner may also use TELEGRAM_CHAT_ID."""
    tenant = tenancy.tenant_of(db)
    if tenant is None:
        return env_chat_id()
    user = db.query(models.User).filter(models.User.id == tenant).first()
    if user is not None and user.telegram_chat_id:
        return user.telegram_chat_id
    return env_chat_id() if owner_user_id(db) == tenant else None


def user_for_chat(db: Session, chat_id: str) -> tuple[bool, Optional[int]]:
    """(found, user_id) for a Telegram chat. user_id None with found=True means the single-user tenant."""
    if not tenancy.auth_enabled():
        return (True, None) if env_chat_id() and chat_id == env_chat_id() else (False, None)
    user = db.query(models.User).filter(models.User.telegram_chat_id == chat_id, models.User.is_active == True).first()  # noqa: E712
    if user is not None:
        return True, user.id
    if env_chat_id() and chat_id == env_chat_id():
        owner = owner_user_id(db)
        if owner is not None:
            return True, owner
    return False, None


def new_telegram_link_code(db: Session, user: models.User) -> tuple[str, int]:
    code = secrets.token_urlsafe(9).replace("=", "")
    user.telegram_link_code = code
    user.telegram_link_expires = _utcnow() + datetime.timedelta(minutes=LINK_CODE_MINUTES)
    db.commit()
    return code, LINK_CODE_MINUTES * 60


def link_telegram_chat(db: Session, code: str, chat_id: str) -> Optional[models.User]:
    """Attach `chat_id` to the user who generated `code` (once, within 15 minutes). A chat belongs to one user."""
    if not code or len(code) > 64:
        return None
    user = db.query(models.User).filter(models.User.telegram_link_code == code).first()
    if user is None or not user.telegram_link_expires or user.telegram_link_expires < _utcnow():
        return None
    db.query(models.User).filter(models.User.telegram_chat_id == chat_id, models.User.id != user.id) \
        .update({"telegram_chat_id": None}, synchronize_session=False)
    user.telegram_chat_id = chat_id
    user.telegram_link_code, user.telegram_link_expires = None, None
    db.commit()
    return user
