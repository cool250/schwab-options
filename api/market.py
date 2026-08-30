from fastapi import APIRouter, Depends
from service import MarketService

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
