"""Web-facing hardening for the app: response security headers and keeping
login tokens out of the logs. Wired up in api/app.py."""

import base64
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request

# ─── Tokens in logs ────────────────────────────────────────────────────
# The Analyze page's WebSocket carries the login token as ?token=… (a
# handshake can't send an Authorization header), and uvicorn logs every
# connection's full path — on Fly, straight into `fly logs`.

_TOKEN_PARAM = re.compile(r"([?&]token=)[^&\s\"']*")


def redact_tokens(text: str) -> str:
    return _TOKEN_PARAM.sub(r"\1<redacted>", text)


class RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_tokens(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def install_log_redaction() -> None:
    """uvicorn.error logs WebSocket connections ("WebSocket /path?query"
    [accepted]); uvicorn.access logs HTTP requests the same way."""
    for name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(RedactTokenFilter())


# ─── Security headers ──────────────────────────────────────────────────

def inline_script_hashes(index_html: Path) -> List[str]:
    """CSP hashes for index.html's inline scripts (the theme script that
    runs before React, so there's no flash of the wrong theme)."""
    if not index_html.is_file():
        return []
    html = index_html.read_text(encoding="utf-8")
    hashes = []
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        hashes.append(f"'sha256-{digest}'")
    return hashes


def content_security_policy(script_hashes: List[str]) -> str:
    """Everything the SPA loads is its own (bundled scripts, styles, fonts,
    images); the API and the Analyze WebSocket are same-origin. Inline
    styles stay allowed — chart libraries set them — but inline scripts
    only by hash, so an injected <script> can't run and read the token."""
    return "; ".join([
        "default-src 'self'",
        "script-src " + " ".join(["'self'", *script_hashes]),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def security_headers(csp: str) -> dict:
    return {
        "Content-Security-Policy": csp,
        # Fly forces HTTPS; browsers ignore this header over plain http (local dev).
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }


def install_security_headers(app: FastAPI, index_html: Path) -> None:
    """Add the headers to every response — API routes and the SPA's files
    alike — unless a route set one itself."""
    headers = security_headers(content_security_policy(inline_script_hashes(index_html)))

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


# ─── API docs ──────────────────────────────────────────────────────────

def api_docs_urls() -> dict:
    """FastAPI's docs_url / redoc_url / openapi_url. The interactive docs are
    for local development only: in production they'd hand anyone a map of
    every route. Fly sets FLY_APP_NAME on every machine."""
    enabled = not os.getenv("FLY_APP_NAME")
    return {
        "docs_url": "/docs" if enabled else None,
        "redoc_url": "/redoc" if enabled else None,
        "openapi_url": "/openapi.json" if enabled else None,
    }
