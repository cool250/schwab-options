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
    stock_ticker: str,
    start_date: str,
    end_date: str,
    contract_type: str = "PUT",
    realized_gains_only: bool = False,
    service: TransactionService = Depends(get_service),
):
    return service.get_option_transactions(
        stock_ticker, start_date, end_date, contract_type, realized_gains_only
    )
