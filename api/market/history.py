"""Price history for Charts."""

from fastapi import APIRouter, Depends

from service.market import MarketService

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


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
