from dotenv import load_dotenv
load_dotenv()

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_log_dir = Path(__file__).resolve().parent.parent / "logs"
_log_dir.mkdir(exist_ok=True)

def _resolve_log_level() -> int:
    _mapping = logging.getLevelNamesMapping()
    if "--log-level" in sys.argv:
        idx = sys.argv.index("--log-level")
        if idx + 1 < len(sys.argv):
            return _mapping.get(sys.argv[idx + 1].upper(), logging.INFO)
    return logging.INFO

_log_level = _resolve_log_level()

_log_handlers: list[logging.Handler] = [
    logging.handlers.RotatingFileHandler(
        _log_dir / "api.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
    ),
]
# On a container host (Fly.io) the log file lives inside the machine, while
# `fly logs` only shows stdout — LOG_TO_STDOUT mirrors every record there too.
if os.getenv("LOG_TO_STDOUT", "").lower() in ("1", "true", "yes"):
    _log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)

logging.getLogger(__name__).info("Log level: %s", logging.getLevelName(_log_level))

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from broker.schwab.exceptions import BrokerAuthError, BrokerError
from broker.tastytrade import TastytradeAPIError
from service.market.errors import UNAVAILABLE_MESSAGE, MarketDataError, SymbolNotFound
from api import users
from api.admin import router as admin_router
from api.auth import router as auth_router, require_admin, require_auth
from broker.schwab.auth import require_token_owner
from api.copilot import router as copilot_router
from api.market import router as market_router, stream_router as market_stream_router
from api.portfolio import router as portfolio_router


class _SPAStaticFiles(StaticFiles):
    """Serve a React SPA: fall back to index.html for unknown paths so
    client-side routing continues to work after a hard refresh. Unknown
    /api paths stay a 404: an HTML 200 there would read as a broken JSON
    response instead of a missing route."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not (path == "api" or path.startswith("api/")):
                return await super().get_response("index.html", scope)
            raise


app = FastAPI(
    title="Options Wheel API",
    version="1.0.0",
    description="REST API for the Options Wheel trading application.",
)


@app.exception_handler(BrokerAuthError)
async def broker_auth_error_handler(request: Request, exc: BrokerAuthError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})

# A transient broker-side failure (e.g. Schwab returning 503s after retries)
# is not an auth problem — FastAPI dispatches to the most specific handler by
# exception type, so BrokerAuthError still hits the 503 handler above; every
# other BrokerError (e.g. PositionService._require_snapshot surfacing a
# fetch failure instead of silently degrading to an empty portfolio) lands
# here as a 502 so the frontend can show it as a system error distinct from
# "please re-authenticate".
@app.exception_handler(BrokerError)
async def broker_error_handler(request: Request, exc: BrokerError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})

# Market data (Tastytrade). service/market/errors.py maps every broker
# failure to one of these: a symbol with nothing listed is a 404; anything
# else is a 502 with a fixed message — the real cause is logged, never sent
# to the browser.
@app.exception_handler(SymbolNotFound)
async def symbol_not_found_handler(request: Request, exc: SymbolNotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(MarketDataError)
async def market_data_error_handler(request: Request, exc: MarketDataError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# A raw Tastytrade error that escaped translation — still a 502, still
# without its text.
@app.exception_handler(TastytradeAPIError)
async def tastytrade_error_handler(request: Request, exc: TastytradeAPIError):
    logging.getLogger(__name__).error("Untranslated Tastytrade error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": UNAVAILABLE_MESSAGE})

# Multi-user: accounts live in SQLite next to the Schwab token store (see
# api/users.py), and every Schwab call must belong to a logged-in user —
# require_token_owner() makes a call with no user context fail instead of
# silently using the admin's token (broker/schwab/auth/token_provider.py).
users.init_db()
require_token_owner()

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])
app.include_router(market_router, prefix="/api/market", tags=["Market"], dependencies=[Depends(require_auth)])
# Not gated by Depends(require_auth) — a WebSocket handshake carries no
# Authorization header, so this route verifies the token itself (passed as a
# query param) inside the handler instead.
app.include_router(market_stream_router, prefix="/api/market/ws", tags=["Market"])
app.include_router(portfolio_router, prefix="/api/portfolio", dependencies=[Depends(require_auth)])
# Copilot is admin-only: it's billed to the admin's OpenAI key.
app.include_router(copilot_router, prefix="/api/copilot", tags=["Copilot"], dependencies=[Depends(require_admin)])

# Serve the React SPA from frontend/dist when it has been built (production).
# This mount must come AFTER all API routers so API routes take priority.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_dist), html=True), name="frontend")