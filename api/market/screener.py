"""The Screener: top options/strategies to sell or buy across tickers."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.market.params import normalize_symbol
from service.market import MarketService
from service.market.models import ScreenerResult, ScreenerStrategy
from service.market.screener_strategies import STRATEGIES, list_strategies

router = APIRouter()

StrategyId = Literal[STRATEGIES]
MAX_TICKERS = 25


def get_service() -> MarketService:
    return MarketService()


@router.get("/options/screener/strategies", summary="The screener's strategy choices", response_model=list[ScreenerStrategy])
def get_screener_strategies():
    return list_strategies()


@router.get(
    "/options/screener",
    summary="Top options/strategies to sell (by annualized ROI) or buy (by leverage)",
    response_model=ScreenerResult,
    response_model_exclude_unset=True,
)
def screen_options(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. 'AAPL,MSFT,/ES'"),
    min_dte: int = Query(0, ge=0, le=365),
    max_dte: int = Query(7, ge=0, le=365),
    min_moneyness: float = Query(..., ge=-100, le=100, description="Min percent OTM (negative = ITM)"),
    max_moneyness: float = Query(..., ge=-100, le=100, description="Max percent OTM (negative = ITM)"),
    strategy: StrategyId = Query(
        "PUT",
        description="PUT / CALL (short), LONG_PUT / LONG_CALL, or a multi-leg credit Strategy Builder template "
                    "(see /options/screener/strategies)",
    ),
    min_delta: Optional[float] = Query(None, ge=0, le=1, description="Min absolute delta (puts and calls alike); omit for no lower bound"),
    max_delta: Optional[float] = Query(None, ge=0, le=1, description="Max absolute delta; omit for no upper bound"),
    limit: int = Query(200, ge=1, le=1000),
    service: MarketService = Depends(get_service),
):
    tickers = []
    for raw in symbols.split(","):
        if not raw.strip():
            continue
        try:
            tickers.append(normalize_symbol(raw))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{raw.strip()[:20]}' isn't a valid ticker")
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        raise HTTPException(status_code=422, detail="Enter at least one ticker")
    if len(tickers) > MAX_TICKERS:
        raise HTTPException(status_code=422, detail=f"Screen at most {MAX_TICKERS} tickers at a time")
    if min_dte > max_dte:
        raise HTTPException(status_code=422, detail="Min DTE must not exceed Max DTE")
    if min_moneyness > max_moneyness:
        raise HTTPException(status_code=422, detail="Min moneyness must not exceed Max moneyness")
    if min_delta is not None and max_delta is not None and min_delta > max_delta:
        raise HTTPException(status_code=422, detail="Min delta must not exceed Max delta")
    return service.screen_options(
        tickers, min_dte, max_dte, min_moneyness, max_moneyness, strategy, min_delta, max_delta, limit
    )
