"""Portfolio routes (/api/portfolio) — the user's own account data from
their broker (Schwab). Never prices anything Schwab can't: the page gets
those prices from /api/market/quotes."""

from fastapi import APIRouter

from . import positions, transactions

router = APIRouter()
router.include_router(positions.router, prefix="/positions", tags=["Portfolio: positions"])
router.include_router(transactions.router, prefix="/transactions", tags=["Portfolio: transactions"])

__all__ = ["router"]
