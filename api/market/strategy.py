"""The Analyze page's Strategy Builder."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from service.market import MarketService
from service.market.strategy_builder import StrategyParamError

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


class LegParam(BaseModel):
    mode: str
    value: Optional[float] = None


class StrategyBuildRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    dte: int = Field(..., ge=0, le=1000)
    expirationDate: Optional[str] = None
    # Optional end of an expiration range: build on every listed expiration
    # with dte in [dte, maxDte] and rank them together.
    maxDte: Optional[int] = Field(None, ge=0, le=1000)
    strategy: str
    # Leg key -> placement; legs left out use the template's default.
    params: dict[str, LegParam] = {}
    # Per share: minimum net credit (credit strategies) or maximum net debit
    # (debit strategies). Omit for no target.
    target: Optional[float] = Field(None, ge=0)


@router.get("/strategies", summary="Strategy Builder templates (legs, defaults, placement modes)")
def get_strategy_templates(service: MarketService = Depends(get_service)):
    return service.get_strategy_templates()


@router.post("/strategy/build", summary="Place a strategy's legs on the live chain (mid prices)")
def build_strategy(body: StrategyBuildRequest, service: MarketService = Depends(get_service)):
    symbol = body.symbol.strip().upper()
    try:
        result = service.build_strategy(
            symbol,
            body.dte,
            body.strategy.strip().upper(),
            {k: v.model_dump() for k, v in body.params.items()},
            body.target,
            body.expirationDate,
            body.maxDte,
        )
    except StrategyParamError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"No option chain found for {symbol}")
    return result
