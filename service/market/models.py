"""What Market routes return — the API's response models. Field names are
camelCase because that's the contract the pages already read.

Routes serialize with response_model_exclude_unset, so a field a row
doesn't carry is absent rather than null — e.g. a long-option screener row
has no "roi". A field that's present but unknown (no quote, no greeks) is
null.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# --- Chains ---

class Expiration(BaseModel):
    date: str  # "YYYY-MM-DD"
    dte: int


class ChainContract(BaseModel):
    symbol: Optional[str] = None  # dxFeed streamer symbol — also the live stream's quote key
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    iv: Optional[float] = None  # this contract's own IV, a fraction
    volume: Optional[float] = None
    openInterest: Optional[float] = None


class ChainRow(BaseModel):
    strikePrice: float
    call: Optional[ChainContract] = None
    put: Optional[ChainContract] = None


class OptionChain(BaseModel):
    symbol: Optional[str] = None
    spot: float
    dte: Optional[int] = None
    expirationDate: str
    iv: Optional[float] = None  # chain-level: the ATM call/put average
    chain: list[ChainRow]


# --- Charts ---

class Candle(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None


class PriceHistory(BaseModel):
    symbol: str
    range: str
    candles: list[Candle]
    support: list[float]
    resistance: list[float]


# --- Strategy Builder ---

class LegParam(BaseModel):
    mode: str
    value: Optional[float] = None


class TemplateLeg(BaseModel):
    key: str
    role: Literal["anchor", "wing", "same"]
    type: Literal["PUT", "CALL"]
    qty: int  # signed per unit: positive = bought
    label: str
    default: Optional[LegParam] = None  # anchors and wings
    of: Optional[str] = None  # wings and "same" legs: the leg they're placed from
    dir: Optional[int] = None  # wings: +1 = higher strike, -1 = lower


class StrategyTemplate(BaseModel):
    id: str
    name: str
    direction: Literal["credit", "debit"]
    description: str
    legs: list[TemplateLeg]
    order: list[tuple[str, str]]
    anchorModes: list[str]
    wingModes: list[str]


class BuiltLeg(BaseModel):
    key: str
    label: str
    symbol: Optional[str] = None
    type: Literal["PUT", "CALL"]
    strike: float
    qty: int
    bid: float
    ask: float
    mid: float
    delta: Optional[float] = None
    iv: Optional[float] = None
    otmPct: float


class StrategyCandidate(BaseModel):
    legs: list[BuiltLeg]
    netPremium: float  # per share, one unit; positive = net credit
    naturalPremium: float
    maxProfit: Optional[float] = None  # None = unbounded
    maxLoss: Optional[float] = None
    breakevens: list[float]
    pop: Optional[float] = None
    returnOnRisk: Optional[float] = None
    annualizedReturn: Optional[float] = None
    pnlAtSpot: float
    netDelta: Optional[float] = None
    distance: int  # strikes moved from the requested placement
    expirationDate: Optional[str] = None
    dte: int
    iv: Optional[float] = None


class StrategyBuild(BaseModel):
    symbol: str
    strategy: str
    spot: float
    iv: Optional[float] = None
    dte: Optional[int] = None
    expirationDate: Optional[str] = None
    expirationsSearched: int
    best: Optional[StrategyCandidate] = None
    alternatives: list[StrategyCandidate]
    reasons: list[str]
    params: dict[str, LegParam]


# --- Screener ---

class _ContractFields(BaseModel):
    symbol: str
    type: Literal["PUT", "CALL"]
    expirationDate: Optional[str] = None
    dte: Optional[int] = None
    strike: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    iv: Optional[float] = None
    volume: Optional[float] = None
    openInterest: Optional[float] = None
    underlying: str
    spot: float
    mid: Optional[float] = None
    otmPct: float
    premium: float
    breakeven: float


class ShortOptionRow(_ContractFields):
    strategy: Literal["PUT", "CALL"]
    capital: float
    roi: float  # percent
    annualizedRoi: float  # percent — the sort key


class LongOptionRow(_ContractFields):
    strategy: Literal["LONG_PUT", "LONG_CALL"]
    leverage: Optional[float] = None
    breakevenMovePct: float


class ComboLeg(BaseModel):
    symbol: str
    type: Literal["PUT", "CALL"]
    strike: float
    qty: int
    price: float  # the fill used: bid when sold, ask when bought
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None


class ComboRow(BaseModel):
    symbol: str  # "qty:symbol|…" — unique per combination
    strategy: Literal["RATIO_PUT", "JADE_LIZARD"]
    underlying: str
    spot: float
    expirationDate: Optional[str] = None
    dte: Optional[int] = None
    legs: list[ComboLeg]
    credit: float
    maxProfit: Optional[float] = None
    capital: float
    breakevens: list[float]
    lowerBreakeven: Optional[float] = None
    shortDelta: Optional[float] = None
    roi: float
    annualizedRoi: float


ScreenerRow = Annotated[Union[ShortOptionRow, LongOptionRow, ComboRow], Field(discriminator="strategy")]


class ScreenerError(BaseModel):
    symbol: str
    message: str


class ScreenerResult(BaseModel):
    results: list[ScreenerRow]
    totalMatches: int
    errors: list[ScreenerError]
    truncated: list[str]  # tickers whose contract list hit the cap
