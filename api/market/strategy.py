"""The Analyze page's Strategy Builder."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.market.params import Symbol
from service.market import MarketService
from service.market.models import LegParam, StrategyBuild, StrategyTemplate
from service.market.strategy_builder import StrategyParamError

router = APIRouter()


def get_service() -> MarketService:
    return MarketService()


class StrategyBuildRequest(BaseModel):
    symbol: Symbol
    dte: int = Field(..., ge=0, le=1000)
    # The expiration the user picked — built on exactly this date. Without
    # it, the listing closest to `dte`.
    expirationDate: Optional[date] = None
    # Optional end of an expiration range: build on every listed expiration
    # with dte in [dte, maxDte] and rank them together.
    maxDte: Optional[int] = Field(None, ge=0, le=1000)
    strategy: str = Field(..., min_length=1, max_length=40)
    # Leg key -> placement; legs left out use the template's default.
    params: dict[str, LegParam] = {}
    # Per share: minimum net credit (credit strategies) or maximum net debit
    # (debit strategies). Omit for no target.
    target: Optional[float] = Field(None, ge=0)


@router.get("/strategies", summary="Strategy Builder templates (legs, defaults, placement modes)",
            response_model=list[StrategyTemplate], response_model_exclude_unset=True)
def get_strategy_templates(service: MarketService = Depends(get_service)):
    return service.get_strategy_templates()


@router.post("/strategy/build", summary="Place a strategy's legs on the live chain (mid prices)",
             response_model=StrategyBuild, response_model_exclude_unset=True)
def build_strategy(body: StrategyBuildRequest, service: MarketService = Depends(get_service)):
    try:
        result = service.build_strategy(
            body.symbol,
            body.dte,
            body.strategy.strip().upper(),
            {k: v.model_dump() for k, v in body.params.items()},
            body.target,
            body.expirationDate.isoformat() if body.expirationDate else None,
            body.maxDte,
        )
    except StrategyParamError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if result is None:
        on = f" on {body.expirationDate.isoformat()}" if body.expirationDate and not body.maxDte else ""
        raise HTTPException(status_code=404, detail=f"No option chain found for {body.symbol}{on}")
    return result
