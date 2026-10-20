"""Input types shared by the Market routes, so every one validates a symbol
the same way (and FastAPI rejects a bad one with a 422 naming the field)."""

import re
from typing import Annotated

from pydantic import AfterValidator

# An equity/ETF/index ticker ("SPY", "BRK/B", "SPX") or a futures root with
# its leading slash ("/ES").
_SYMBOL = re.compile(r"^/?[A-Z][A-Z0-9./]{0,11}$")


def normalize_symbol(value: str) -> str:
    value = value.strip().upper()
    if not _SYMBOL.match(value):
        raise ValueError("must be a ticker like SPY or a futures root like /ES")
    return value


Symbol = Annotated[str, AfterValidator(normalize_symbol)]
