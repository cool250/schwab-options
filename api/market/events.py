"""Upcoming market events for the Home page: economic releases, FOMC
decisions, and earnings / ex-dividend dates for the tickers the page sends."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.market.params import normalize_symbol
from service.market import EventService

router = APIRouter()

MAX_SYMBOLS = 100


def get_service() -> EventService:
    return EventService()


class MarketEvent(BaseModel):
    date: str                       # YYYY-MM-DD
    time: Optional[str] = None      # "HH:MM", US Eastern; None when unknown
    name: str
    kind: Literal["ECONOMIC", "FOMC", "EARNINGS", "EX_DIVIDEND"]
    symbol: Optional[str] = None    # the ticker, for earnings and ex-dividend
    major: bool = False             # CPI, jobs, PCE, FOMC
    detail: Optional[str] = None


class EventsResponse(BaseModel):
    events: list[MarketEvent]
    notes: list[str]                # sources that were unavailable, and why


@router.get("/events", summary="Upcoming economic releases, FOMC decisions, and earnings / ex-dividend dates",
            response_model=EventsResponse)
def get_events(
    symbols: str = Query("", description="Comma-separated tickers for earnings and ex-dividend dates; may be empty"),
    days: int = Query(14, ge=1, le=60),
    service: EventService = Depends(get_service),
):
    tickers = []
    for raw in symbols.split(","):
        if not raw.strip():
            continue
        try:
            tickers.append(normalize_symbol(raw))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{raw.strip()[:20]}' isn't a valid ticker")
    if len(set(tickers)) > MAX_SYMBOLS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_SYMBOLS} tickers")
    return service.upcoming(tickers, days)
