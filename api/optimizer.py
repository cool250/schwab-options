from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Query
from service.optimizer import WheelOptimizer

router = APIRouter()


@router.get("/", summary="Wheel optimizer — best OTM options to sell")
def get_recommendations(
    extra_symbols: Optional[str] = Query(
        None,
        description="Comma-separated extra tickers to scan for puts (e.g. 'SPY,QQQ')",
    ),
    max_dte: int = Query(7, ge=1, le=60, description="Maximum days to expiration"),
):
    symbols = [s.strip().upper() for s in extra_symbols.split(",")] if extra_symbols else None
    recs = WheelOptimizer(max_dte=max_dte).optimize(extra_symbols=symbols)
    rows = [asdict(r) for r in recs]
    calls = [r for r in rows if r["option_type"] == "CALL"]
    puts = [r for r in rows if r["option_type"] == "PUT"]
    return {"calls": calls, "puts": puts}
