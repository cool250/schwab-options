"""The broker seam for Portfolio flows: what a broker must provide, in a
broker-neutral shape.

PositionService and TransactionService only ever talk to these Protocols,
never to a broker SDK — so a broker is one module implementing them (see
schwab.py) plus one registry entry (see __init__.py).

Futures and futures-option *positions* aren't part of this seam: no
broker's positions endpoint returns them in this app (Schwab's doesn't), so
the services reconstruct them from transaction history
(TransactionProvider below).
"""

from typing import Optional, Protocol

from pydantic import BaseModel


# ─── The leg shape providers return ──────────────────────────────────

class OptionTransaction(BaseModel):
    """One option leg (TransactionProvider.fetch_option_legs), and the
    matched trade the matcher builds from an open + close pair."""
    date: str
    close_date: str
    underlying_symbol: str
    expirationDate: str
    strike_price: float
    symbol: str
    price: float
    open_price: float = 0.0
    close_price: float = 0.0
    amount: float
    position_effect: Optional[str] = None
    option_type: str
    type: str
    # "EXPIRATION" | "ASSIGNMENT" | "EXERCISE" | None — how a closing leg
    # closed, classified by the provider (see TransactionProvider).
    close_event: Optional[str] = None
    total_amount: Optional[float] = 0.0
    open_type: Optional[str] = None


# ─── The seam ──────────────────────────────────────────────────────────

class PositionProvider(Protocol):
    """Balances, positions, quotes and the accounts a login covers — for the
    account selected for this request (broker.request_context)."""

    def get_account_snapshot(self) -> dict:
        """Current balances + positions (equities, ETFs, options — not
        futures, see module docstring), normalized to a broker-neutral shape:

        {
          "balances": {
              "margin_balance": float | None,
              "cash_balance": float | None,
              "mutual_fund_value": float | None,
              "liquidation_value": float | None,
          } | None,   # None only if the account has no balances section at all
          "positions": [
              {
                  "asset_type": "EQUITY" | "OPTION" | "COLLECTIVE_INVESTMENT",
                  "symbol": str,                 # broker-native trading symbol
                  "long_quantity": float,
                  "short_quantity": float,
                  "average_price": float | None,
                  "tax_lot_long_price": float | None,
                  "tax_lot_short_price": float | None,
                  "long_open_pl": float | None,
                  "short_open_pl": float | None,
                  # Option-only (parsed from the option symbol); None for equities:
                  "underlying_symbol": str | None,
                  "strike_price": float | None,
                  "expiration_date": str | None,   # "YYYY-MM-DD"
                  "option_type": str | None,        # "P" | "C"
              }, ...
          ],
        }

        Raises BrokerAuthError/BrokerError (broker.exceptions) on fetch
        failure — never returns partial data silently; callers decide how to
        degrade.
        """
        ...

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        """Live mark price per symbol (the broker-native symbols the snapshot
        returned). Any symbol whose quote can't be fetched is simply omitted
        from the result."""
        ...

    def list_accounts(self) -> list[dict]:
        """Every account the user's broker login covers, in the broker's own
        order (the first is the default until the user picks one):

        [{
            "id": str,          # opaque and safe to send to the browser
            "number": str,      # full account number — server-side only
            "type": str | None, # e.g. "MARGIN", "CASH"
            "value": float | None,  # liquidation value
            "positions": int,
        }, ...]

        The provider honors the chosen account by reading
        broker.request_context.get_selected_account(), which holds a
        `number` from this list."""
        ...


class TransactionProvider(Protocol):
    """Transaction history for the account selected for this request."""

    def fetch_raw_transactions(self, start_date: str, end_date: str) -> list:
        """Broker-native transaction records, verbatim — backs the "raw
        transaction history" endpoint. Deliberately NOT normalized; shape is
        provider-specific by design. Must be JSON-serializable (a pydantic
        model or plain dict/list)."""
        ...

    def fetch_option_legs(self, start_date: str, end_date: str) -> list[dict]:
        """Every option leg in the window, one dict per leg, not filtered by
        ticker/contract type (callers filter the result):
        {date, close_date, underlying_symbol, expirationDate, strike_price,
         symbol, price, amount, position_effect, option_type,
         type: "TRADE",   # broker-neutral "not yet triaged" sentinel —
                           # matching logic in the service promotes this to
                           # CLOSED/EXPIRED/ASSIGNED/EXERCISED once matched
         close_event: "EXPIRATION" | "ASSIGNMENT" | "EXERCISE" | None,
         total_amount, open_price, close_price, open_type}
        close_event classifies a closing leg from whatever the broker
        records (see SchwabTransactionProvider._identify_close_event) —
        "EXERCISE" is a futures option exercised into its future, whose
        premium is kept as P&L (the future is booked at the strike)."""
        ...

    def fetch_equity_future_legs(self, start_date: str, end_date: str) -> list[dict]:
        """Every equity/futures fill in the window, one dict per leg, not
        filtered by ticker/asset type (callers filter the result):
        {date, symbol, asset_type: "EQUITY"|"FUTURE", amount, price, cost}.
        cost is already multiplier-adjusted, credit-positive/debit-negative."""
        ...

    def normalize_futures_symbol(self, symbol: str) -> str:
        """Collapse a broker-native futures/futures-option symbol to its
        bare CME root (e.g. 'ES', 'NQ'). Non-futures symbols pass through
        unchanged. On the Protocol because
        TransactionService.get_equity_transactions calls it on the final
        display symbol only after FIFO matching — matching itself stays
        keyed on the exact contract symbol."""
        ...
