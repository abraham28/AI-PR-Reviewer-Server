"""Admin session auth: signed cookie, login/logout, dependency."""
from __future__ import annotations

import base64
import hmac
import hashlib
import os
import time

from fastapi import Request, HTTPException
from fastapi.responses import Response

SESSION_COOKIE = "pr_reviewer_session"
SESSION_DAYS = 7


def _admin_password() -> str:
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def auth_enabled() -> bool:
    return bool(_admin_password())


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie_value(secret: str) -> str:
    expiry = int(time.time()) + SESSION_DAYS * 24 * 3600
    payload = str(expiry)
    raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = _sign(payload, secret)
    return f"{raw}.{sig}"


def verify_session_cookie(cookie_value: str, secret: str) -> bool:
    if not cookie_value or "." not in cookie_value:
        return False
    raw, sig = cookie_value.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(raw + "==").decode()
        expiry = int(payload)
        if expiry <= time.time():
            return False
        return hmac.compare_digest(sig, _sign(payload, secret))
    except Exception:
        return False


def get_session_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def require_admin(request: Request) -> None:
    """Raise 401 if auth is enabled and request has no valid session."""
    if not auth_enabled():
        return
    secret = _admin_password()
    cookie = get_session_cookie(request)
    if not cookie or not verify_session_cookie(cookie, secret):
        raise HTTPException(status_code=401, detail="Authentication required")


def set_session_cookie(response: Response, secret: str, secure: bool = False) -> None:
    value = create_session_cookie_value(secret)
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
