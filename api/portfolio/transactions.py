from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from service.portfolio import TransactionService
from service.portfolio.ratio_spreads import group_ratio_spreads as group_ratio_spread_trades

router = APIRouter()

# Typed parameters: FastAPI rejects a missing/malformed date or an unknown
# filter with a 422 that says which field is wrong, instead of the service
# failing on it with a 500.
ContractType = Literal["PUT", "CALL", "ALL"]
AssetType = Literal["EQUITY", "FUTURE", "ALL"]


def get_service() -> TransactionService:
    return TransactionService()


def _range(start_date: date, end_date: date) -> tuple[str, str]:
    """The services take ISO strings; reject an inverted range up front."""
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    return start_date.isoformat(), end_date.isoformat()


@router.get("/", summary="Raw transaction history")
def get_transaction_history(
    start_date: date,
    end_date: date,
    service: TransactionService = Depends(get_service),
):
    return service.get_transaction_history(*_range(start_date, end_date))


@router.get("/options", summary="Parsed and matched option transactions")
def get_option_transactions(
    start_date: date,
    end_date: date,
    stock_ticker: str = "",
    contract_type: ContractType = "ALL",
    realized_gains_only: bool = False,
    unrealized_only: bool = False,
    group_ratio_spreads: bool = False,
    service: TransactionService = Depends(get_service),
):
    trades = service.get_option_transactions(
        stock_ticker, *_range(start_date, end_date), contract_type, realized_gains_only, unrealized_only
    )
    if group_ratio_spreads:
        trades = group_ratio_spread_trades(trades)
    return trades


@router.get("/equity", summary="FIFO-matched buy/sell round-trips for equities and outright futures")
def get_equity_transactions(
    start_date: date,
    end_date: date,
    stock_ticker: str = "",
    asset_type: AssetType = "ALL",
    realized_gains_only: bool = False,
    service: TransactionService = Depends(get_service),
):
    return service.get_equity_transactions(
        stock_ticker, *_range(start_date, end_date), asset_type, realized_gains_only
    )
