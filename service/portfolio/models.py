"""What Portfolio flows return: typed rows with numbers, not display strings.

Formatting ($, commas, decimals) is the UI's job. These models are both the
services' return types and the API's response models, so the contract is
explicit, documented in /docs, and checked on the way out. A value that
isn't known (no live quote yet, no broker cost basis) is None, never 0.
"""

from typing import Optional

from pydantic import BaseModel


class Balances(BaseModel):
    # Cash, or the margin balance when that's negative (money borrowed).
    cash_balance: Optional[float] = None
    mutual_fund_value: Optional[float] = None
    # Liquidation value of the whole account.
    account_value: Optional[float] = None


class StockPosition(BaseModel):
    symbol: str
    quantity: float                     # signed: negative = short
    trade_price: Optional[float] = None # average cost per share
    # The broker's own tax-lot-aware cost basis and unrealized P&L — can
    # differ from trade_price (wash sales, non-FIFO lot methods).
    broker_cost_basis: Optional[float] = None
    broker_pl: Optional[float] = None
    current_price: Optional[float] = None


class OptionPosition(BaseModel):
    ticker: str
    symbol: str                         # broker-native contract symbol
    strike_price: float
    expiration_date: Optional[str] = None   # "YYYY-MM-DD"
    days_to_expiry: Optional[int] = None
    quantity: float                     # contracts, signed: negative = short
    exposure: float = 0.0               # short puts: strike x 100 x contracts
    trade_price: Optional[float] = None # per share
    current_price: Optional[float] = None
    # Unrealized P&L in dollars (short/credit positive); None when there's
    # no live quote — never priced at $0.
    total_value: Optional[float] = None


class FuturesPosition(BaseModel):
    symbol: str                         # root, e.g. "ES"
    quantity: float                     # contracts, signed
    trade_price: float                  # average entry price


class SpreadLeg(BaseModel):
    strike_price: float
    amount: float                       # contracts on this side (unsigned)
    trade_price: float
    symbol: Optional[str] = None


class FuturesOptionPosition(BaseModel):
    ticker: str                         # root, e.g. "ES"
    symbol: str                         # contract symbol (synthetic for a ratio spread)
    expiration_date: Optional[str] = None
    days_to_expiry: Optional[int] = None
    # A single contract has strike_price and quantity; a grouped ratio
    # spread has neither — it has ratio ("1:2") and long_leg/short_leg.
    strike_price: Optional[float] = None
    quantity: Optional[float] = None
    ratio: Optional[str] = None
    trade_price: float                  # per point; a spread's net entry price
    # Entry value in dollars (trade_price x quantity x multiplier; credit
    # positive) — the page reprices it at the live quote for P&L.
    total_value: float
    multiplier: int
    long_leg: Optional[SpreadLeg] = None
    short_leg: Optional[SpreadLeg] = None


class PositionsSummary(BaseModel):
    """GET /api/portfolio/positions/ — the equity tab in one call."""
    puts: list[OptionPosition]
    calls: list[OptionPosition]
    balances: Balances
    stocks: list[StockPosition]


class OptionPositions(BaseModel):
    puts: list[OptionPosition]
    calls: list[OptionPosition]


class FuturesOptionPositions(BaseModel):
    puts: list[FuturesOptionPosition]
    calls: list[FuturesOptionPosition]
