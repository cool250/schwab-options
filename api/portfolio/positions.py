from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import users
from api.auth import require_auth
from api.users import User
from service.portfolio import PositionService
from service.portfolio.models import (
    Balances,
    FuturesOptionPositions,
    FuturesPosition,
    OptionPositions,
    PositionsSummary,
    StockPosition,
)
from service.portfolio.providers import get_broker, get_position_provider, is_registered, list_brokers

router = APIRouter()


def get_service() -> PositionService:
    return PositionService()


@router.get("/", summary="All positions, balances, and stocks", response_model=PositionsSummary)
def populate_positions(service: PositionService = Depends(get_service)):
    (puts, calls), balances, stocks = service.populate_positions()
    return PositionsSummary(puts=puts, calls=calls, balances=balances, stocks=stocks)


@router.get("/balances", summary="Account balances", response_model=Balances)
def get_balances(service: PositionService = Depends(get_service)):
    return service.get_balances()


@router.get("/stocks", summary="Stock / ETF positions", response_model=list[StockPosition])
def get_stock_position(service: PositionService = Depends(get_service)):
    return service.get_stock_position()


@router.get(
    "/stocks/trade-basis",
    summary="Per-share price of each stock position as its own fills were priced (null where history doesn't cover it) — unlike average_price, without assigned options' premium folded in",
    response_model=dict[str, Optional[float]],
)
def get_stock_trade_basis(service: PositionService = Depends(get_service)):
    return service.get_stock_trade_basis()


@router.get(
    "/futures",
    summary="Open futures positions, derived from transaction history (Schwab's positions API doesn't return futures) — no current_price: the page prices them via POST /api/market/quotes",
    response_model=list[FuturesPosition],
)
def get_futures_position(service: PositionService = Depends(get_service)):
    return service.get_futures_position()


@router.get(
    "/futures/options",
    summary="Open futures-option positions (puts and calls), derived from transaction history — no current_price: the page prices each contract via POST /api/market/quotes",
    response_model=FuturesOptionPositions,
)
def get_futures_option_position(service: PositionService = Depends(get_service)):
    puts, calls = service.get_futures_option_position()
    return FuturesOptionPositions(puts=puts, calls=calls)


@router.get("/options", summary="Open option positions (puts and calls)", response_model=OptionPositions)
def get_option_position(service: PositionService = Depends(get_service)):
    puts, calls = service.get_option_position()
    return OptionPositions(puts=puts, calls=calls)


@router.get("/exposure", summary="Total dollar exposure by ticker", response_model=dict[str, float])
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


def _brokers_for(user: User) -> list[dict]:
    active = get_broker(user.broker).name
    return [{"name": b.name, "label": b.label, "selected": b.name == active} for b in list_brokers()]


@router.get("/brokers", summary="Brokers Portfolio data can come from, with the one this user reads marked selected")
def get_brokers(user: User = Depends(require_auth)):
    return _brokers_for(user)


class BrokerChoice(BaseModel):
    name: str  # a broker's "name" from GET /brokers


@router.put("/broker", summary="Choose which broker Positions, Transactions and Reports read")
def set_broker(choice: BrokerChoice, user: User = Depends(require_auth)):
    if not is_registered(choice.name):
        raise HTTPException(status_code=404, detail="That broker isn't available.")
    if choice.name != get_broker(user.broker).name:
        users.set_broker(user.id, choice.name)  # also clears the chosen account
    return _brokers_for(users.get_user(user.id))

