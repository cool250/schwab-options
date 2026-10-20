"""Synthetic market data for Market tests: a Black-Scholes-shaped chain
(spot 105, strikes 80-130 every $1, 25% IV) — realistic enough that delta,
moneyness and premium placement behave like a real chain."""

import math

SPOT, IV, DTE = 105.0, 0.25, 30


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(strike, is_call, spot=SPOT, iv=IV, dte=DTE):
    t = dte / 365
    d1 = (math.log(spot / strike) + iv * iv / 2 * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    if is_call:
        return spot * _ncdf(d1) - strike * _ncdf(d2), _ncdf(d1)
    return strike * _ncdf(-d2) - spot * _ncdf(-d1), _ncdf(d1) - 1


def contract(strike, type_, spread=0.10, dte=DTE, expiration="2026-11-20"):
    price, delta = bs(strike, type_ == "CALL", dte=dte)
    bid = max(round(price - spread / 2, 2), 0.0)
    return {
        "symbol": f".X{expiration}{type_[0]}{strike:g}", "type": type_, "strike": float(strike),
        "bid": bid, "ask": round(bid + spread, 2), "delta": round(delta, 4), "iv": IV,
        "dte": dte, "expirationDate": expiration, "volume": 0, "openInterest": 0,
    }


def make_chain(strikes=range(80, 131), dte=DTE, expiration="2026-11-20"):
    """OptionChainProvider.get_option_chain shape."""
    rows = []
    for k in strikes:
        call, put = contract(k, "CALL", dte=dte, expiration=expiration), contract(k, "PUT", dte=dte, expiration=expiration)
        rows.append({"strikePrice": float(k), "call": call, "put": put})
    return {"symbol": "X", "spot": SPOT, "dte": dte, "expirationDate": expiration, "iv": IV, "chain": rows}


class FakeChainProvider:
    """Serves synthetic chains; `screener` maps symbol -> contracts (or an
    Exception to raise)."""

    def __init__(self, chains=None, screener=None, expirations=None):
        self.chains = chains or {}
        self.screener = screener or {}
        self.expirations = expirations or []
        self.calls = []

    def get_option_chain(self, symbol, dte=None, strike_count=20, expiration_date=None, spot=None):
        self.calls.append(("chain", symbol, dte, expiration_date))
        if expiration_date is not None:
            return self.chains.get(expiration_date)
        return min(self.chains.values(), key=lambda c: abs(c["dte"] - dte), default=None)

    def get_expirations(self, symbol, days_ahead=60):
        return [e for e in self.expirations if e["dte"] <= days_ahead]

    def get_screener_contracts(self, symbol, min_dte, max_dte, option_types, min_otm_pct, max_otm_pct):
        value = self.screener.get(symbol)
        if isinstance(value, Exception):
            raise value
        if value is None:
            return None
        contracts = [c for c in value if c["type"] in option_types]
        return {"symbol": symbol, "spot": SPOT, "truncated": False, "contracts": contracts}
