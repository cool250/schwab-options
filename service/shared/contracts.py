"""Broker-neutral contract facts, imported by both Portfolio and Market:
contract multipliers and OCC option-symbol parsing. No broker imports here."""

import logging

logger = logging.getLogger(__name__)

# Contract multipliers (points per contract) for non-standard underlyings —
# CME contract specs, the same whichever broker reports the trade.
CONTRACT_MULTIPLIER = {
    "ES": 50,
    "NQ": 20,
}


def get_contract_multiplier(underlying_symbol: str) -> int:
    return CONTRACT_MULTIPLIER.get(underlying_symbol, 100)


def parse_option_symbol(symbol: str):
    """Parse an OCC option symbol (the industry-standard format, e.g.
    'SPY   260918P00675000') into (ticker, strike_price, expiration_date).

    expiration_date is full 4-digit-year ISO ("2026-09-18"), matching the
    convention used everywhere else in the app (futures options,
    Transactions' expirationDate) — the OCC symbol itself only carries a
    2-digit year.
    """
    try:
        strike_price = float(symbol[13:21]) / 1000
        ticker = symbol[:6].strip()
        expiration_date = f"20{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
        return ticker, strike_price, expiration_date
    except ValueError as e:
        logger.error(f"Error parsing option symbol {symbol}: {e}")
        return None, None, None
