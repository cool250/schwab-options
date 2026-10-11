import os
from typing import Optional
import hmac
import hashlib
import logging
import secrets
import time
import base64
from datetime import datetime, timezone
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from api import users
from api.users import User
from broker.schwab.auth.authenticate import build_authorize_url, exchange_authorization_code
from broker.schwab.auth.token_provider import create_token_provider, set_token_owner

logger = logging.getLogger(__name__)

router = APIRouter()
_bearer = HTTPBearer()

_TOKEN_TTL = 8 * 3600  # 8 hours


def _secret_key() -> bytes:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return key.encode()


def _make_token(user_id: int) -> str:
    """Login token: "u<user id>:<issued unix time in ms>", HMAC-signed.
    Milliseconds, not seconds, so "issued before/after the last password
    change" is unambiguous even within the same second."""
    payload = f"u{user_id}:{int(time.time() * 1000)}"
    sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{sig}"


def _verify_token(token: str) -> Optional[User]:
    """The user a login token belongs to, or None. Beyond the signature and
    8-hour TTL, the account must still exist and be enabled, and the token
    must postdate the user's last password change — so disabling an account
    or resetting its password signs that user out everywhere."""
    try:
        encoded, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded).decode()
        expected_sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        uid_str, ts_str = payload.split(":", 1)
        if not uid_str.startswith("u"):
            return None  # pre-multi-user token format ("<username>:<ts>")
        issued = int(ts_str) / 1000
        if time.time() - issued > _TOKEN_TTL:
            return None
        user = users.get_user(int(uid_str[1:]))
        if user is None or user.disabled or issued < user.password_changed_at:
            return None
        return user
    except Exception:
        return None


async def require_auth(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> User:
    """Bearer-token auth for every protected route; returns the user and
    records them as the owner of this request's Schwab calls.

    Async on purpose: FastAPI runs sync dependencies in a separate worker
    thread, and a ContextVar set there would never reach the route handler.
    Set here (in the request's own context), it does — FastAPI copies the
    context into the handler's thread."""
    user = _verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    set_token_owner(user.id)
    return user


async def require_admin(user: User = Depends(require_auth)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return user


def verify_token(token: str) -> bool:
    """Public wrapper for WebSocket routes, which can't carry an Authorization
    header the way HTTPBearer expects — they pass the token as a query param
    and check it manually instead of via the require_auth dependency."""
    return _verify_token(token) is not None


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    # users.authenticate takes the same time for an unknown username as for
    # a wrong password, and treats a disabled account as invalid — the
    # response never reveals which of the three it was.
    user = users.authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return {"token": _make_token(user.id), "user": user.public()}


@router.get("/me")
def me(user: User = Depends(require_auth)):
    return user.public()


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


@router.post("/password")
def change_password(req: ChangePasswordRequest, user: User = Depends(require_auth)):
    """Change your own password. Signs out your other sessions; returns a
    fresh token so this one stays logged in."""
    if users.authenticate(user.username, req.currentPassword) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    try:
        users.set_password(user.id, req.newPassword)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"token": _make_token(user.id)}


# ─── Schwab reconnect (Settings → Reconnect Schwab) ──────────────────────
# Schwab's refresh token dies 7 days after the login that issued it and can
# only be replaced by logging in again. Instead of running main.py and
# copying token.json to the server, the app runs that OAuth flow itself:
# /schwab/start (login-protected) hands the browser Schwab's login URL with
# a signed `state`; Schwab redirects back to /schwab/callback — the URL set
# as SCHWAB_APP_CALLBACK_URL and registered in Schwab's developer portal —
# which exchanges the code and saves the tokens via the normal token store.

_OAUTH_STATE_TTL = 10 * 60  # long enough to log in at Schwab, short enough to be useless later


def _oauth_state_key() -> bytes:
    # Derived from SECRET_KEY but distinct from the login-token key: a state
    # value travels through Schwab and lands in the browser's URL/history,
    # so it must never verify as an app login token (_verify_token).
    return hmac.new(_secret_key(), b"schwab-oauth-state", hashlib.sha256).digest()


def _make_oauth_state(user_id: int) -> str:
    # The user id rides along (signed) so the callback — which can't carry a
    # login token — knows whose Schwab token store to save into.
    payload = f"{user_id}:{secrets.token_urlsafe(16)}:{int(time.time())}"
    sig = hmac.new(_oauth_state_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{base64.urlsafe_b64encode(payload.encode()).decode()}.{sig}"


def _verify_oauth_state(state: str) -> Optional[int]:
    """The user id a valid, unexpired state was issued for, else None."""
    try:
        encoded, sig = state.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded).decode()
        expected = hmac.new(_oauth_state_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        user_id, _nonce, ts = payload.split(":")
        if time.time() - int(ts) > _OAUTH_STATE_TTL:
            return None
        return int(user_id)
    except Exception:
        return None


@router.get("/schwab/status", dependencies=[Depends(require_auth)])
def schwab_status():
    """Whether a Schwab token is stored and when its refresh token expires
    (None when unknown — a token saved before issue times were tracked)."""
    provider = create_token_provider()
    expires_at = provider.refresh_token_expires_at()
    return {
        "connected": provider.has_tokens(),
        "refreshTokenExpiresAt": (
            datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat() if expires_at else None
        ),
        "expired": expires_at is not None and expires_at <= time.time(),
    }


@router.get("/schwab/start")
def schwab_start(user: User = Depends(require_auth)):
    """Schwab login URL for the browser to navigate to (a fetch with the
    Bearer header can't follow a cross-site redirect, so the URL is returned
    rather than redirected to)."""
    return {"url": build_authorize_url(_make_oauth_state(user.id))}


def _back_to_settings(**params: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?{urlencode(params)}", status_code=303)


@router.get("/schwab/callback")
def schwab_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Where Schwab redirects after login. No Bearer header is possible on
    a cross-site redirect, so the signed `state` from /schwab/start is what
    proves this flow was started by the logged-in user."""
    user_id = _verify_oauth_state(state) if state else None
    if user_id is None:
        logger.warning("Schwab callback rejected: missing/invalid/expired state")
        return _back_to_settings(schwab="error", reason="The reconnect link expired or was invalid. Try again.")
    user = users.get_user(user_id)
    if user is None or user.disabled:
        return _back_to_settings(schwab="error", reason="Your account is no longer active.")
    if error or not code:
        return _back_to_settings(schwab="error", reason=error or "Schwab didn't return an authorization code.")
    try:
        tokens = exchange_authorization_code(code)
        create_token_provider(user.id).save_tokens(tokens)
    except Exception as e:
        logger.error("Schwab reconnect failed: %s", e)
        return _back_to_settings(schwab="error", reason=f"Schwab rejected the login: {e}")
    logger.info("Schwab reconnected via the in-app flow (user %s)", user.id)
    return _back_to_settings(schwab="connected")

