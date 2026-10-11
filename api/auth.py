import os
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

from broker.schwab.auth.authenticate import build_authorize_url, exchange_authorization_code
from broker.schwab.auth.token_provider import create_token_provider

logger = logging.getLogger(__name__)

router = APIRouter()
_bearer = HTTPBearer()

_TOKEN_TTL = 8 * 3600  # 8 hours


def _secret_key() -> bytes:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return key.encode()


def _make_token(username: str) -> str:
    ts = str(int(time.time()))
    payload = f"{username}:{ts}"
    sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{sig}"


def _verify_token(token: str) -> bool:
    try:
        encoded, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded).decode()
        expected_sig = hmac.new(_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        ts_str = payload.rsplit(":", 1)[1]
        if time.time() - int(ts_str) > _TOKEN_TTL:
            return False
        return True
    except Exception:
        return False


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    if not _verify_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_token(token: str) -> bool:
    """Public wrapper for WebSocket routes, which can't carry an Authorization
    header the way HTTPBearer expects — they pass the token as a query param
    and check it manually instead of via the require_auth dependency."""
    return _verify_token(token)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    expected_username = os.getenv("ADMIN_USERNAME", "")
    expected_password = os.getenv("ADMIN_PASSWORD", "")

    # Always compare both fields to prevent timing-based username enumeration
    username_ok = hmac.compare_digest(req.username, expected_username)
    password_ok = hmac.compare_digest(req.password, expected_password)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return {"token": _make_token(req.username)}


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


def _make_oauth_state() -> str:
    payload = f"{secrets.token_urlsafe(16)}:{int(time.time())}"
    sig = hmac.new(_oauth_state_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{base64.urlsafe_b64encode(payload.encode()).decode()}.{sig}"


def _verify_oauth_state(state: str) -> bool:
    try:
        encoded, sig = state.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded).decode()
        expected = hmac.new(_oauth_state_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        return time.time() - int(payload.rsplit(":", 1)[1]) <= _OAUTH_STATE_TTL
    except Exception:
        return False


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


@router.get("/schwab/start", dependencies=[Depends(require_auth)])
def schwab_start():
    """Schwab login URL for the browser to navigate to (a fetch with the
    Bearer header can't follow a cross-site redirect, so the URL is returned
    rather than redirected to)."""
    return {"url": build_authorize_url(_make_oauth_state())}


def _back_to_settings(**params: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?{urlencode(params)}", status_code=303)


@router.get("/schwab/callback")
def schwab_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Where Schwab redirects after login. No Bearer header is possible on
    a cross-site redirect, so the signed `state` from /schwab/start is what
    proves this flow was started by the logged-in user."""
    if not state or not _verify_oauth_state(state):
        logger.warning("Schwab callback rejected: missing/invalid/expired state")
        return _back_to_settings(schwab="error", reason="The reconnect link expired or was invalid. Try again.")
    if error or not code:
        return _back_to_settings(schwab="error", reason=error or "Schwab didn't return an authorization code.")
    try:
        tokens = exchange_authorization_code(code)
        create_token_provider().save_tokens(tokens)
    except Exception as e:
        logger.error("Schwab reconnect failed: %s", e)
        return _back_to_settings(schwab="error", reason=f"Schwab rejected the login: {e}")
    logger.info("Schwab reconnected via the in-app flow")
    return _back_to_settings(schwab="connected")

