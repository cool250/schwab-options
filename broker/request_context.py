"""Per-request broker context that isn't specific to one broker.

The broker a request's Portfolio data comes from: api/auth.require_auth
sets the one the user chose in Settings (a registered name, see
service/portfolio/providers), and the provider registry resolves it.
None = the default broker.

The account a request reads: when a user's broker login covers several
accounts, api/auth.require_auth sets the one they chose (the full account
number from PositionProvider.list_accounts, saved per user), and each
broker's client reads it when resolving which account to call. None = the
broker's first account.
"""

from contextvars import ContextVar, Token
from typing import Optional

_selected_broker: ContextVar[Optional[str]] = ContextVar("selected_broker", default=None)
_selected_account: ContextVar[Optional[str]] = ContextVar("selected_account", default=None)


def set_selected_broker(name: Optional[str]) -> Token:
    return _selected_broker.set(name)


def get_selected_broker() -> Optional[str]:
    return _selected_broker.get()


def set_selected_account(account_number: Optional[str]) -> Token:
    return _selected_account.set(account_number)


def get_selected_account() -> Optional[str]:
    return _selected_account.get()
