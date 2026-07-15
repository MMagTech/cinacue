"""Administrator authentication.

Design goals (foundation):

* Single admin, password stored only as a bcrypt hash in the config dir.
* No default password. The account is seeded from ADMIN_PASSWORD on first run.
* Session carried in a signed, HTTP-only, SameSite=Lax cookie.
* Double-submit CSRF token required for all admin write actions.
* Simple in-memory rate limiting on login attempts.

Nothing here is returned to public clients. The app secret used for signing is
generated once and persisted alongside the config so sessions survive restarts.
"""
from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.context import CryptContext

from .config import settings

SESSION_COOKIE = "mc_session"
CSRF_HEADER = "X-CSRF-Token"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

# Public viewer access (shared code) — a separate, long-lived cookie so friends
# only enter the code occasionally, with its own gentler lockout.
ACCESS_COOKIE = "cc_access"
ACCESS_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
_ACCESS_MAX_ATTEMPTS = 8
_ACCESS_WINDOW_SECONDS = 15 * 60  # 15-minute lockout window

# Rate limiting: max attempts per window per client key.
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_login_attempts: Dict[str, Deque[float]] = defaultdict(deque)
_access_attempts: Dict[str, Deque[float]] = defaultdict(deque)


# --- App secret ------------------------------------------------------------
def _load_or_create_secret() -> str:
    path = settings.secret_path
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - non-posix fs
        pass
    return secret


_serializer = URLSafeTimedSerializer(_load_or_create_secret(), salt="mc-session")


# --- Password storage ------------------------------------------------------
def admin_password_is_set() -> bool:
    return settings.admin_hash_path.exists()


def set_admin_password(password: str) -> None:
    if not password:
        raise ValueError("password must not be empty")
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.admin_hash_path.write_text(_pwd.hash(password), encoding="utf-8")
    try:
        settings.admin_hash_path.chmod(0o600)
    except OSError:  # pragma: no cover
        pass


def verify_password(password: str) -> bool:
    if not admin_password_is_set():
        return False
    stored = settings.admin_hash_path.read_text(encoding="utf-8").strip()
    return _pwd.verify(password, stored)


def seed_admin_from_env() -> None:
    """Create the admin account from ADMIN_PASSWORD if none exists yet."""
    if admin_password_is_set():
        return
    if settings.admin_password:
        set_admin_password(settings.admin_password)


# --- Rate limiting ---------------------------------------------------------
def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    now = time.time()
    key = _client_key(request)
    attempts = _login_attempts[key]
    while attempts and now - attempts[0] > _WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )


def record_failed_attempt(request: Request) -> None:
    _login_attempts[_client_key(request)].append(time.time())


def reset_attempts(request: Request) -> None:
    _login_attempts.pop(_client_key(request), None)


# --- Sessions & CSRF -------------------------------------------------------
def _new_csrf() -> str:
    return secrets.token_urlsafe(32)


def start_session(response: Response) -> str:
    """Issue a session cookie and return the CSRF token to hand to the client."""
    csrf = _new_csrf()
    token = _serializer.dumps({"auth": True, "csrf": csrf})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,  # True behind TLS in production
        path="/",
    )
    return csrf


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --- Public viewer access (shared code) ------------------------------------
def public_access_required() -> bool:
    """True when a shared viewer code is configured (viewer is gated)."""
    return bool((settings.public_access_code or "").strip())


def verify_access_code(code: str) -> bool:
    expected = (settings.public_access_code or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(code.strip(), expected)


def grant_public_access(response: Response) -> None:
    """Issue the long-lived viewer-access cookie after a correct code."""
    token = _serializer.dumps({"access": True}, salt="cc-access")
    response.set_cookie(
        ACCESS_COOKIE,
        token,
        max_age=ACCESS_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def has_public_access(request: Request) -> bool:
    """True if the viewer may watch: gate disabled, admin session, or valid code."""
    if not public_access_required():
        return True
    if is_authenticated(request):  # the admin can always watch
        return True
    raw = request.cookies.get(ACCESS_COOKIE)
    if not raw:
        return False
    try:
        data = _serializer.loads(raw, max_age=ACCESS_MAX_AGE, salt="cc-access")
    except BadSignature:
        return False
    return bool(data and data.get("access"))


def check_access_rate_limit(request: Request) -> None:
    now = time.time()
    key = _client_key(request)
    attempts = _access_attempts[key]
    while attempts and now - attempts[0] > _ACCESS_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _ACCESS_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in a little while.",
        )


def record_access_failure(request: Request) -> None:
    _access_attempts[_client_key(request)].append(time.time())


def reset_access_attempts(request: Request) -> None:
    _access_attempts.pop(_client_key(request), None)


def _read_session(request: Request) -> dict | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return _serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def is_authenticated(request: Request) -> bool:
    data = _read_session(request)
    return bool(data and data.get("auth"))


def session_csrf(request: Request) -> str | None:
    """Return the CSRF token bound to the current session, if authenticated.

    Lets the SPA re-arm its in-memory CSRF token after a page reload (when the
    session cookie survives but the token held in JS memory is lost), so write
    actions don't fail until the user logs in again.
    """
    data = _read_session(request)
    if data and data.get("auth"):
        return data.get("csrf")
    return None


def require_admin(request: Request) -> None:
    """Dependency: reject unauthenticated requests."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def require_csrf(request: Request) -> None:
    """Dependency for write actions: session + matching CSRF header."""
    data = _read_session(request)
    if not data or not data.get("auth"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    sent = request.headers.get(CSRF_HEADER, "")
    expected = data.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
