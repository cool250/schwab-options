"""Home's watchlist: last price, change on the day, day range and IV for the
tickers the page sends (its positions')."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.market.params import normalize_symbol
from service.market import WatchlistService

router = APIRouter()

MAX_SYMBOLS = 60


def get_service() -> WatchlistService:
    return WatchlistService()


class WatchlistRow(BaseModel):
    symbol: str
    price: Optional[float] = None
    change: Optional[float] = None          # vs the previous close
    change_pct: Optional[float] = None
    prev_close: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    iv: Optional[float] = None              # implied volatility, percent (equities and ETFs)
    iv_rank: Optional[float] = None         # IV rank, percent


@router.get("/watchlist", summary="Last price, change on the day, day range and IV for each ticker",
            response_model=list[WatchlistRow])
def get_watchlist(
    symbols: str = Query(..., description="Comma-separated tickers or futures roots, e.g. 'GOOG,QQQ,/ES'"),
    service: WatchlistService = Depends(get_service),
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
    if len(tickers) > MAX_SYMBOLS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_SYMBOLS} tickers")
    return service.rows(tickers)
