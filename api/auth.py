import os
import hmac
import hashlib
import time
import base64
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

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
