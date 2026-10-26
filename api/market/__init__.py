"""Market routes (/api/market) — Tastytrade-backed market data. No
Portfolio data here, and no Schwab connection needed."""

from fastapi import APIRouter

from . import chains, events, history, quotes, screener, strategy
from .stream import router as stream_router

router = APIRouter()
for _module in (chains, screener, strategy, history, quotes, events):
    router.include_router(_module.router)

__all__ = ["router", "stream_router"]
