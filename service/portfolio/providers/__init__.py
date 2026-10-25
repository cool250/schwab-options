"""Portfolio broker registry — the one place that decides which broker
Portfolio flows read.

Each user picks theirs in Settings (saved per user as `broker`, see
api/users.py); api/auth.require_auth puts it on the request
(broker.request_context), and get_broker() resolves it here. A user who
hasn't chosen, or whose saved broker isn't registered, reads DEFAULT_BROKER.

Adding a broker:
  1. Write service/portfolio/providers/<broker>.py with classes implementing
     PositionProvider and TransactionProvider (base.py) — see schwab.py.
  2. register() it below. It then appears in Settings' broker choice
     (GET /api/portfolio/positions/brokers).
  3. Give it a connect flow and per-user credential storage, the way
     api/auth.py's /api/auth/schwab/* and broker/schwab/auth do for Schwab,
     and a connection check for the Portfolio pages (today RequireSchwab).
Nothing in PositionService, TransactionService or the API routes changes:
they only see the Protocols. A test double is a third implementation:
pass it straight to PositionService(provider=...) / TransactionService(...).
"""

from dataclasses import dataclass
from typing import Callable, Optional

from broker.request_context import get_selected_broker
from service.portfolio.providers.base import PositionProvider, TransactionProvider
from service.portfolio.providers.schwab import SchwabPositionProvider, SchwabTransactionProvider


@dataclass(frozen=True)
class PortfolioBroker:
    name: str           # stored per user; stable, lowercase
    label: str          # shown in Settings
    positions: Callable[[], PositionProvider]
    transactions: Callable[[], TransactionProvider]


_BROKERS: dict[str, PortfolioBroker] = {}


def register(broker: PortfolioBroker) -> None:
    _BROKERS[broker.name] = broker


register(PortfolioBroker("schwab", "Schwab", SchwabPositionProvider, SchwabTransactionProvider))

# What a user reads until they choose otherwise.
DEFAULT_BROKER = "schwab"


def list_brokers() -> list[PortfolioBroker]:
    return list(_BROKERS.values())


def is_registered(name: Optional[str]) -> bool:
    return name in _BROKERS


def get_broker(name: Optional[str] = None) -> PortfolioBroker:
    """The named broker, else this request's user's choice, else the
    default — an unregistered name (e.g. one since removed) falls back too."""
    chosen = name or get_selected_broker()
    return _BROKERS[chosen] if chosen in _BROKERS else _BROKERS[DEFAULT_BROKER]


def get_position_provider() -> PositionProvider:
    return get_broker().positions()


def get_transaction_provider() -> TransactionProvider:
    return get_broker().transactions()


__all__ = [
    "PositionProvider", "TransactionProvider", "PortfolioBroker", "DEFAULT_BROKER",
    "register", "list_brokers", "is_registered", "get_broker", "get_position_provider", "get_transaction_provider",
]
