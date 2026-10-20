"""Price history for Charts."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from api.market.params import Symbol
from service.market import MarketService
from service.market.models import PriceHistory

router = APIRouter()

Range = Literal["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"]


def get_service() -> MarketService:
    return MarketService()


@router.get("/price-history", summary="OHLC candles + support/resistance for a Charts-page timeframe button", response_model=PriceHistory)
def get_price_history(symbol: Symbol, range: Range = "1M", service: MarketService = Depends(get_service)):
    history = service.get_price_history(symbol, range)
    if history is None:
        raise HTTPException(status_code=404, detail=f"No price history found for {symbol}")
    return history
