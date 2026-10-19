from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import users
from api.auth import require_auth
from api.users import User
from service import PositionService
from service.portfolio.providers import get_position_provider

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


@router.get(
    "/futures",
    summary="Open futures positions, derived from transaction history (Schwab's positions API doesn't return futures) — no current_price, see /futures/quotes",
)
def get_futures_position(service: PositionService = Depends(get_service)):
    return service.get_futures_position()


@router.get(
    "/futures/quotes",
    summary="Live current prices for open outright futures positions, keyed by symbol (slow — Tastytrade DXLink)",
)
def get_futures_quotes(service: PositionService = Depends(get_service)):
    return service.get_futures_quotes()


@router.get(
    "/futures/options",
    summary="Open futures-option positions (puts and calls), derived from transaction history — no current_price, see /futures/options/quotes",
)
def get_futures_option_position(service: PositionService = Depends(get_service)):
    puts, calls = service.get_futures_option_position()
    return {"puts": puts, "calls": calls}


@router.get(
    "/futures/options/quotes",
    summary="Live current prices for open futures-option positions, keyed by symbol (slow — Tastytrade DXLink per expiration)",
)
def get_futures_option_quotes(service: PositionService = Depends(get_service)):
    return service.get_futures_option_quotes()


@router.get("/options", summary="Open option positions (puts and calls)")
def get_option_position(service: PositionService = Depends(get_service)):
    puts, calls = service.get_option_position()
    return {"puts": puts, "calls": calls}


@router.get("/exposure", summary="Total dollar exposure by ticker")
def get_total_exposure(service: PositionService = Depends(get_service)):
    return service.get_total_exposure()


# ─── Accounts (the account picker) ───────────────────────────────────────

def _accounts_for(user: User) -> list[dict]:
    """The accounts the user's broker login covers, for the account picker.
    Full account numbers stay server-side: the browser gets a masked label
    and the provider's opaque id to choose by."""
    accounts = get_position_provider().list_accounts()
    numbers = [a["number"] for a in accounts]
    # The account Portfolio actually reads: the saved one while still part
    # of the login, else the broker's first (same rule the provider applies).
    active = user.broker_account if user.broker_account in numbers else (numbers[0] if numbers else None)
    return [
        {
            "id": a["id"],
            "label": f"…{str(a['number'])[-4:]}",
            "type": a["type"],
            "value": a["value"],
            "positions": a["positions"],
            "selected": a["number"] == active,
        }
        for a in accounts
    ]


@router.get("/accounts", summary="Accounts the broker login covers, with the one Portfolio reads marked selected")
def get_accounts(user: User = Depends(require_auth)):
    return _accounts_for(user)


class AccountChoice(BaseModel):
    id: str  # an account's "id" from GET /accounts


@router.put("/account", summary="Choose which account Positions, Transactions and Reports read")
def set_account(choice: AccountChoice, user: User = Depends(require_auth)):
    match = next((a for a in get_position_provider().list_accounts() if a["id"] == choice.id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="That account isn't part of your broker login.")
    users.set_broker_account(user.id, match["number"])
    return _accounts_for(users.get_user(user.id))
