from dotenv import load_dotenv
load_dotenv()

import logging
import logging.handlers
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

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            _log_dir / "api.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
        ),
    ],
)

logging.getLogger(__name__).info("Log level: %s", logging.getLevelName(_log_level))

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from api.auth import router as auth_router, require_auth
from api.market import router as market_router
from api.position import router as position_router
from api.transactions import router as transactions_router
from api.agent import router as agent_router


class _SPAStaticFiles(StaticFiles):
    """Serve a React SPA: fall back to index.html for unknown paths so
    client-side routing continues to work after a hard refresh."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


app = FastAPI(
    title="Options Wheel API",
    version="1.0.0",
    description="REST API for the Options Wheel trading application.",
)

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(market_router, prefix="/api/market", tags=["Market"], dependencies=[Depends(require_auth)])
app.include_router(position_router, prefix="/api/positions", tags=["Positions"], dependencies=[Depends(require_auth)])
app.include_router(transactions_router, prefix="/api/transactions", tags=["Transactions"], dependencies=[Depends(require_auth)])
app.include_router(agent_router, prefix="/api/agent", tags=["Agent"], dependencies=[Depends(require_auth)])

# Serve the React SPA from frontend/dist when it has been built (production).
# This mount must come AFTER all API routers so API routes take priority.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_dist), html=True), name="frontend")

