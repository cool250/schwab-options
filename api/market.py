from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from service import MarketService
from service.screener_strategies import STRATEGIES

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


@router.get("/options/expiration-list", summary="All available expiration dates for a symbol")
def get_expiration_list(
    symbol: str,
    days_ahead: int = 60,
    service: MarketService = Depends(get_service),
):
    return service.get_expirations(symbol, days_ahead)


@router.get("/options/chain", summary="Normalized option chain for a DTE")
def get_option_chain(
    symbol: str,
    dte: int = 7,
    service: MarketService = Depends(get_service),
):
    chain = service.get_option_chain(symbol, dte)
    if chain is None:
        return {"message": "No option chain found"}
    return chain


@router.get("/options/screener", summary="Top options/strategies to sell (by annualized ROI) or buy (by leverage)")
def screen_options(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. 'AAPL,MSFT,/ES'"),
    min_dte: int = Query(0, ge=0, le=365),
    max_dte: int = Query(7, ge=0, le=365),
    min_moneyness: float = Query(..., ge=-100, le=100, description="Min percent OTM (negative = ITM)"),
    max_moneyness: float = Query(..., ge=-100, le=100, description="Max percent OTM (negative = ITM)"),
    strategy: str = Query(
        "PUT",
        description="PUT / CALL (short), LONG_PUT / LONG_CALL, RATIO_PUT (1x2 put ratio spread), or JADE_LIZARD",
    ),
    min_delta: Optional[float] = Query(None, ge=0, le=1, description="Min absolute delta (puts and calls alike); omit for no lower bound"),
    max_delta: Optional[float] = Query(None, ge=0, le=1, description="Max absolute delta; omit for no upper bound"),
    limit: int = Query(200, ge=1, le=1000),
    service: MarketService = Depends(get_service),
):
    tickers = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    strategy = strategy.strip().upper()
    if not tickers:
        raise HTTPException(status_code=422, detail="Enter at least one ticker")
    if len(tickers) > 25:
        raise HTTPException(status_code=422, detail="Screen at most 25 tickers at a time")
    if strategy not in STRATEGIES:
        raise HTTPException(status_code=422, detail=f"Option type must be one of: {', '.join(STRATEGIES)}")
    if min_dte > max_dte:
        raise HTTPException(status_code=422, detail="Min DTE must not exceed Max DTE")
    if min_moneyness > max_moneyness:
        raise HTTPException(status_code=422, detail="Min moneyness must not exceed Max moneyness")
    if min_delta is not None and max_delta is not None and min_delta > max_delta:
        raise HTTPException(status_code=422, detail="Min delta must not exceed Max delta")
    return service.screen_options(
        tickers, min_dte, max_dte, min_moneyness, max_moneyness, strategy, min_delta, max_delta, limit
    )


@router.get("/price-history", summary="OHLC candles + support/resistance for a Charts-page timeframe button")
def get_price_history(
    symbol: str,
    range: str = "1M",
    service: MarketService = Depends(get_service),
):
    history = service.get_price_history(symbol, range)
    if history is None:
        return {"message": "No price history found"}
    return history
