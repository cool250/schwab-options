"""Option expirations and chains (Analyze, Charts)."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.market.params import Symbol
from service.market import MarketService
from service.market.models import Expiration, OptionChain

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


@router.get("/options/expiration-list", summary="All listed expiration dates for a symbol", response_model=list[Expiration])
def get_expiration_list(
    symbol: Symbol,
    days_ahead: int = Query(60, ge=0, le=1000),
    service: MarketService = Depends(get_service),
):
    return service.get_expirations(symbol, days_ahead)


@router.get(
    "/options/chain",
    summary="One expiration's chain: exactly `expiration`, or the listing closest to `dte`",
    response_model=OptionChain,
    response_model_exclude_unset=True,
)
def get_option_chain(
    symbol: Symbol,
    dte: Optional[int] = Query(None, ge=0, le=1000),
    expiration: Optional[date] = None,
    service: MarketService = Depends(get_service),
):
    if dte is None and expiration is None:
        raise HTTPException(status_code=422, detail="Pass an expiration date or a dte")
    chain = service.get_option_chain(symbol, dte, expiration_date=expiration.isoformat() if expiration else None)
    if chain is None:
        raise HTTPException(status_code=404, detail=f"No option chain found for {symbol}")
    return chain
