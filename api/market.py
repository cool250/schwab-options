from fastapi import APIRouter, Depends
from service import MarketService

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


@router.get("/price/{symbol}", summary="Get current ticker price")
def get_ticker_price(symbol: str, service: MarketService = Depends(get_service)):
    price = service.get_ticker_price(symbol)
    return {"symbol": symbol, "price": price}


@router.get("/history/{symbol}", summary="Get price history")
def get_price_history(
    symbol: str,
    period_type: str = "month",
    frequency_type: str = "daily",
    period: int = 1,
    service: MarketService = Depends(get_service),
):
    candles = service.get_price_history(symbol, period_type, frequency_type, period)
    return {"symbol": symbol, "candles": candles}


@router.get("/options/best", summary="Best annualized return for a strike")
def highest_return(
    symbol: str,
    strike: float,
    from_date: str,
    to_date: str,
    contract_type: str = "PUT",
    service: MarketService = Depends(get_service),
):
    result = service.highest_return(symbol, strike, from_date, to_date, contract_type)
    if result is None:
        return {"message": "No suitable option found"}
    annualized_return, expiration_date, price = result
    return {
        "annualized_return": annualized_return,
        "expiration_date": expiration_date,
        "price": price,
    }


@router.get("/options/expirations", summary="All expiration dates for a strike")
def get_all_expiration_dates(
    symbol: str,
    strike: float,
    from_date: str,
    to_date: str,
    contract_type: str = "PUT",
    service: MarketService = Depends(get_service),
):
    return service.get_all_expiration_dates(symbol, strike, from_date, to_date, contract_type)
