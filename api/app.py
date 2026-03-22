from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
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

app.include_router(market_router, prefix="/api/market", tags=["Market"])
app.include_router(position_router, prefix="/api/positions", tags=["Positions"])
app.include_router(transactions_router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(agent_router, prefix="/api/agent", tags=["Agent"])

# Serve the React SPA from frontend/dist when it has been built (production).
# This mount must come AFTER all API routers so API routes take priority.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_dist), html=True), name="frontend")

