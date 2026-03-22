from fastapi import APIRouter, Depends
from service import PositionService

router = APIRouter()


def get_service() -> PositionService:
    return PositionService()


@router.get("/", summary="All positions, balances, and stocks")
def populate_positions(service: PositionService = Depends(get_service)):
    option_positions, balances, stocks = service.populate_positions()
    puts, calls = option_positions
    return {"puts": puts, "calls": calls, "balances": balances, "stocks": stocks}


@router.get("/balances", summary="Account balances")
def get_balances(service: PositionService = Depends(get_service)):
    return service.get_balances()


@router.get("/stocks", summary="Stock / ETF positions")
def get_stock_position(service: PositionService = Depends(get_service)):
    return service.get_stock_position()


@router.get("/options", summary="Open option positions (puts and calls)")
def get_option_position(service: PositionService = Depends(get_service)):
    puts, calls = service.get_option_position()
    return {"puts": puts, "calls": calls}


@router.get("/exposure", summary="Total dollar exposure by ticker")
def get_total_exposure(service: PositionService = Depends(get_service)):
    return service.get_total_exposure()
