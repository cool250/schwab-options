"""Live prices for anything a page needs priced that the Portfolio broker
can't quote (futures, futures options) — and the open legs behind
Transactions' unrealized P&L. The page sends the contracts it shows and
combines the prices with its Portfolio data itself."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from service.market import QuoteService

router = APIRouter()


def get_service() -> QuoteService:
    return QuoteService()


class OptionContract(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, description="Caller's id for this contract; the response is keyed by it")
    underlying: str = Field(..., min_length=1, max_length=20, description="'QQQ', or a futures root as '/ES' (or 'ES')")
    expiration: date
    strike: float = Field(..., gt=0)
    type: Literal["PUT", "CALL"]


class QuoteRequest(BaseModel):
    futures: list[str] = Field([], max_length=20, description="Futures roots, e.g. ['ES', 'NQ'] — priced at the front month")
    options: list[OptionContract] = Field([], max_length=500)


class OptionQuote(BaseModel):
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    theta: float | None = None  # per share, per day
    delta: float | None = None  # per share (sign as the option: puts negative)


class QuoteResponse(BaseModel):
    futures: dict[str, float]
    options: dict[str, OptionQuote]


@router.post(
    "/quotes",
    summary="Live prices for futures roots and option contracts (Tastytrade DXLink); anything unpriceable is absent",
    response_model=QuoteResponse,
)
def get_quotes(body: QuoteRequest, service: QuoteService = Depends(get_service)):
    return QuoteResponse(
        futures=service.quote_futures(body.futures),
        options=service.quote_options([c.model_dump() for c in body.options]),
    )
