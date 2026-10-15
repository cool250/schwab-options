from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from service import MarketService
from service.screener_strategies import STRATEGIES
from service.strategy_builder import StrategyParamError

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


class LegParam(BaseModel):
    mode: str
    value: Optional[float] = None


class StrategyBuildRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    dte: int = Field(..., ge=0, le=1000)
    expirationDate: Optional[str] = None
    # Optional end of an expiration range: build on every listed expiration
    # with dte in [dte, maxDte] and rank them together.
    maxDte: Optional[int] = Field(None, ge=0, le=1000)
    strategy: str
    # Leg key -> placement; legs left out use the template's default.
    params: dict[str, LegParam] = {}
    # Per share: minimum net credit (credit strategies) or maximum net debit
    # (debit strategies). Omit for no target.
    target: Optional[float] = Field(None, ge=0)


@router.get("/strategies", summary="Strategy Builder templates (legs, defaults, placement modes)")
def get_strategy_templates(service: MarketService = Depends(get_service)):
    return service.get_strategy_templates()


@router.post("/strategy/build", summary="Place a strategy's legs on the live chain (mid prices)")
def build_strategy(body: StrategyBuildRequest, service: MarketService = Depends(get_service)):
    symbol = body.symbol.strip().upper()
    try:
        result = service.build_strategy(
            symbol,
            body.dte,
            body.strategy.strip().upper(),
            {k: v.model_dump() for k, v in body.params.items()},
            body.target,
            body.expirationDate,
            body.maxDte,
        )
    except StrategyParamError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"No option chain found for {symbol}")
    return result


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
