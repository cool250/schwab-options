from fastapi import APIRouter, Depends
from service import TransactionService

router = APIRouter()


def get_service() -> TransactionService:
    return TransactionService()


@router.get("/", summary="Raw transaction history")
def get_transaction_history(
    start_date: str,
    end_date: str,
    service: TransactionService = Depends(get_service),
):
    return service.get_transaction_history(start_date, end_date)


@router.get("/options", summary="Parsed and matched option transactions")
def get_option_transactions(
    stock_ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    contract_type: str = "PUT",
    realized_gains_only: bool = False,
    unrealized_only: bool = False,
    service: TransactionService = Depends(get_service),
):
    return service.get_option_transactions(
        stock_ticker, start_date, end_date, contract_type, realized_gains_only, unrealized_only
    )


@router.get(
    "/options/quotes",
    summary="Live current prices for open (unrealized) option transactions matching the given filters, keyed by symbol (slow — Tastytrade DXLink)",
)
def get_option_quotes(
    stock_ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    contract_type: str = "PUT",
    service: TransactionService = Depends(get_service),
):
    legs = service.get_option_transactions(
        stock_ticker, start_date, end_date, contract_type,
        realized_gains_only=False, unrealized_only=True,
    )
    return service.get_option_quotes(legs)


@router.get("/equity", summary="FIFO-matched buy/sell round-trips for equities and outright futures")
def get_equity_transactions(
    stock_ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    asset_type: str = "ALL",
    realized_gains_only: bool = False,
    service: TransactionService = Depends(get_service),
):
    return service.get_equity_transactions(
        stock_ticker, start_date, end_date, asset_type, realized_gains_only
    )
