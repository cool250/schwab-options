"""Portfolio broker registry — the one place that decides which broker
Portfolio flows read.

Adding a broker:
  1. Write service/portfolio/providers/<broker>.py with classes implementing
     PositionProvider and TransactionProvider (base.py) — see schwab.py.
  2. register() it below.
  3. Point ACTIVE_BROKER at it (or, to let users pick, store a broker name
     per user next to their chosen account and resolve it in get_broker()).
  4. Give it a connect flow and per-user credential storage, the way
     api/auth.py's /api/auth/schwab/* and broker/schwab/auth do for Schwab.
Nothing in PositionService, TransactionService or the API routes changes:
they only see the Protocols. A test double is a third implementation:
pass it straight to PositionService(provider=...) / TransactionService(...).
"""

from dataclasses import dataclass
from typing import Callable, Optional

from service.portfolio.providers.base import (
    CONTRACT_MULTIPLIER,
    PositionProvider,
    TransactionProvider,
    get_contract_multiplier,
    parse_option_symbol,
)
from service.portfolio.providers.schwab import SchwabPositionProvider, SchwabTransactionProvider


@dataclass(frozen=True)
class PortfolioBroker:
    name: str
    positions: Callable[[], PositionProvider]
    transactions: Callable[[], TransactionProvider]


_BROKERS: dict[str, PortfolioBroker] = {}


def register(broker: PortfolioBroker) -> None:
    _BROKERS[broker.name] = broker


register(PortfolioBroker("schwab", SchwabPositionProvider, SchwabTransactionProvider))

# The broker Portfolio flows read. One today; see the module docstring for
# adding another.
ACTIVE_BROKER = "schwab"


def get_broker(name: Optional[str] = None) -> PortfolioBroker:
    return _BROKERS[name or ACTIVE_BROKER]


def get_position_provider() -> PositionProvider:
    return get_broker().positions()


def get_transaction_provider() -> TransactionProvider:
    return get_broker().transactions()


__all__ = [
    "CONTRACT_MULTIPLIER", "PositionProvider", "TransactionProvider", "PortfolioBroker",
    "get_contract_multiplier", "parse_option_symbol",
    "register", "get_broker", "get_position_provider", "get_transaction_provider", "ACTIVE_BROKER",
]
