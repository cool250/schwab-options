"""Sample brokers for the UI check: a made-up wheel book (stocks, short
options, /ES and /NQ options, a year of closed trades) and Black-Scholes
market data around fixed prices. Deterministic, no network, and nothing
from a real account — the screenshots it produces are safe to share.

Dates are relative to today, so open positions always look open and
Reports always has the last twelve months filled in.
"""

import math
import random
from datetime import date, datetime, timedelta, timezone

from service.shared.contracts import get_contract_multiplier
from utils.market_time import market_today

SPOT = {
    "SPY": 684.20, "QQQ": 612.45, "AAPL": 262.10, "NVDA": 191.35, "TSLA": 441.80,
    "AMD": 243.60, "MSFT": 521.75, "IWM": 248.90, "/ES": 7754.25, "/NQ": 29581.50,
}
IV = {"TSLA": 0.52, "AMD": 0.48, "NVDA": 0.41, "/NQ": 0.21, "/ES": 0.16}
DEFAULT_SPOT, DEFAULT_IV = 100.0, 0.30


def spot_of(symbol: str) -> float:
    return SPOT.get(symbol.upper(), SPOT.get("/" + symbol.upper().lstrip("/"), DEFAULT_SPOT))


def iv_of(symbol: str) -> float:
    s = symbol.upper()
    return IV.get(s, IV.get("/" + s.lstrip("/"), 0.24 if s in SPOT else DEFAULT_IV))


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(spot, strike, dte, iv, is_call):
    """(price, delta) per share."""
    t = max(dte, 0.5) / 365
    d1 = (math.log(spot / strike) + iv * iv / 2 * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    if is_call:
        return spot * _ncdf(d1) - strike * _ncdf(d2), _ncdf(d1)
    return strike * _ncdf(-d2) - spot * _ncdf(-d1), _ncdf(d1) - 1


def theta(spot, strike, dte, iv, is_call):
    today, tomorrow = bs(spot, strike, dte, iv, is_call)[0], bs(spot, strike, max(dte - 1, 0.5), iv, is_call)[0]
    return tomorrow - today


def strike_step(spot: float) -> float:
    return 5.0 if spot < 1000 else 25.0 if spot < 10000 else 50.0


def _day(offset: int) -> str:
    return (market_today() + timedelta(days=offset)).isoformat()


def _friday(offset: int) -> date:
    d = market_today() + timedelta(days=offset)
    return d + timedelta(days=(4 - d.weekday()) % 7)


# ─── Market data (MarketService, QuoteService, watchlist, events) ────────

def expirations(days_ahead=60):
    today = market_today()
    out, d = [], _friday(0)
    while (d - today).days <= days_ahead:
        out.append({"date": d.isoformat(), "dte": (d - today).days})
        d += timedelta(days=7)
    return out


def _contract(symbol, spot, strike, expiration, dte, type_):
    iv = iv_of(symbol) + 0.04 * abs(math.log(strike / spot)) * 10  # a little skew
    price, delta = bs(spot, strike, dte, iv, type_ == "CALL")
    spread = max(0.02, round(price * 0.03, 2))
    bid = max(round(price - spread / 2, 2), 0.01)
    oi = int(4000 * math.exp(-abs(strike / spot - 1) * 30)) + 15
    return {
        "symbol": f".{symbol.lstrip('/')}{expiration.replace('-', '')[2:]}{type_[0]}{strike:g}", "type": type_,
        "strike": float(strike), "bid": bid, "ask": round(bid + spread, 2), "delta": round(delta, 4),
        "iv": round(iv, 4), "dte": dte, "expirationDate": expiration, "volume": oi // 3, "openInterest": oi,
    }


class DemoChainProvider:
    """OptionChainProvider (service/market/chain_providers.py) on synthetic chains."""

    def get_spot(self, symbol):
        return spot_of(symbol)

    def get_expirations(self, symbol, days_ahead=60):
        return expirations(days_ahead)

    def get_option_chain(self, symbol, dte=None, strike_count=20, expiration_date=None, spot=None):
        exps = expirations(90)
        exp = next((e for e in exps if e["date"] == expiration_date), None) if expiration_date else \
            min(exps, key=lambda e: abs(e["dte"] - (dte or 30)))
        if exp is None:
            return None
        spot = spot_of(symbol)
        step = strike_step(spot)
        atm = round(spot / step) * step
        rows = []
        for i in range(-strike_count, strike_count + 1):
            k = atm + i * step
            call, put = (_contract(symbol, spot, k, exp["date"], exp["dte"], t) for t in ("CALL", "PUT"))
            rows.append({"strikePrice": float(k), "call": call, "put": put})
        return {"symbol": symbol, "spot": spot, "dte": exp["dte"], "expirationDate": exp["date"],
                "iv": iv_of(symbol), "chain": rows}

    def get_screener_contracts(self, symbol, min_dte, max_dte, option_types, min_otm_pct, max_otm_pct):
        spot = spot_of(symbol)
        step = strike_step(spot)
        contracts = []
        for exp in expirations(max_dte):
            if exp["dte"] < min_dte:
                continue
            for i in range(-30, 31):
                k = round(spot / step) * step + i * step
                for type_ in option_types:
                    otm = (spot - k) / spot * 100 if type_ == "PUT" else (k - spot) / spot * 100
                    if min_otm_pct <= otm <= max_otm_pct:
                        contracts.append(_contract(symbol, spot, k, exp["date"], exp["dte"], type_))
        return {"symbol": symbol, "spot": spot, "truncated": False, "contracts": contracts}


class DemoMarketClient:
    """The one TastytradeClient method MarketService's Charts history needs."""

    def get_candles(self, symbol, interval, from_ms, regular_hours_only=False, timeout=None):
        step_ms = {"5m": 300_000, "30m": 1_800_000, "1d": 86_400_000, "1mo": 30 * 86_400_000}[interval]
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        times = list(range(from_ms, now_ms, step_ms))
        if interval in ("5m", "30m"):  # 9:30-16:00 New York, weekdays
            times = [t for t in times if datetime.fromtimestamp(t / 1000, timezone.utc).weekday() < 5
                     and 13.5 <= (t // 1000 % 86400) / 3600 < 20]
        rng = random.Random(f"{symbol}{interval}")
        vol = iv_of(symbol) * math.sqrt(step_ms / 86_400_000 / 252)
        closes = [spot_of(symbol)]
        for _ in times[1:]:
            closes.append(closes[-1] / math.exp(rng.gauss(0.0004, vol)))
        closes.reverse()
        bars, prev = [], closes[0]
        for t, c in zip(times, closes):
            hi, lo = max(prev, c) * (1 + abs(rng.gauss(0, vol / 2))), min(prev, c) * (1 - abs(rng.gauss(0, vol / 2)))
            bars.append({"time": t, "open": round(prev, 2), "high": round(hi, 2), "low": round(lo, 2), "close": round(c, 2)})
            prev = c
        return bars


class DemoQuotes:
    """QuoteService stand-in: futures roots and option contracts priced off SPOT."""

    def quote_futures(self, roots):
        return {r: spot_of("/" + r.lstrip("/")) for r in roots}

    def quote_options(self, contracts):
        out = {}
        for c in contracts:
            under = c["underlying"]
            exp = c["expiration"] if isinstance(c["expiration"], str) else c["expiration"].isoformat()
            dte = max((date.fromisoformat(exp) - market_today()).days, 0)
            spot, iv, is_call = spot_of(under), iv_of(under), c["type"] == "CALL"
            price, delta = bs(spot, float(c["strike"]), dte, iv, is_call)
            spread = max(0.02, round(price * 0.03, 2))
            out[c["key"]] = {"bid": round(max(price - spread / 2, 0.01), 2), "ask": round(price + spread / 2, 2),
                             "mid": round(price, 2), "theta": round(theta(spot, float(c["strike"]), dte, iv, is_call), 4),
                             "delta": round(delta, 4), "iv": iv}
        return out


class DemoWatchlist:
    def rows(self, symbols):
        out = []
        for i, s in enumerate(symbols):
            price = spot_of(s)
            change = round(price * (0.012 if i % 3 else -0.0085) * (1 + i % 4) / 2, 2)
            out.append({"symbol": s, "price": price, "change": change, "change_pct": round(change / (price - change) * 100, 2),
                        "prev_close": round(price - change, 2), "day_high": round(price * 1.006, 2),
                        "day_low": round(price * 0.991, 2), "iv": None if s.startswith("/") else round(iv_of(s) * 100, 1),
                        "iv_rank": None if s.startswith("/") else 18.0 + 9 * i % 60})
        return out


class DemoEvents:
    def upcoming(self, symbols, days):
        events = [
            {"date": _day(1), "time": "08:30", "name": "Personal Income and Outlays (PCE)", "kind": "ECONOMIC", "major": True},
            {"date": _day(5), "time": "08:30", "name": "Employment Situation (jobs)", "kind": "ECONOMIC", "major": True},
            {"date": _day(8), "time": "10:00", "name": "JOLTS", "kind": "ECONOMIC", "major": False},
            {"date": _day(12), "time": "08:30", "name": "Consumer Price Index (CPI)", "kind": "ECONOMIC", "major": True},
            {"date": _day(3), "name": "AMD earnings", "kind": "EARNINGS", "symbol": "AMD", "detail": "after close"},
            {"date": _day(9), "name": "NVDA earnings", "kind": "EARNINGS", "symbol": "NVDA", "detail": "after close"},
            {"date": _day(6), "name": "AAPL ex-dividend", "kind": "EX_DIVIDEND", "symbol": "AAPL", "detail": "$0.26"},
        ]
        wanted = {s.upper() for s in symbols}
        return {"events": sorted((e for e in events if int((date.fromisoformat(e["date"]) - market_today()).days) <= days
                                  and (e.get("symbol") is None or e["symbol"] in wanted)), key=lambda e: e["date"]),
                "notes": []}


# ─── Portfolio (the PositionProvider / TransactionProvider seam) ──────────

# (underlying, type, strike, contracts short, days to expiry, premium per share)
OPEN_SHORTS = [
    ("AAPL", "C", 270.0, 3, 8, 2.15), ("NVDA", "C", 200.0, 5, 8, 2.40), ("TSLA", "P", 400.0, 2, 8, 6.90),
    ("AMD", "P", 220.0, 3, 15, 4.10), ("SPY", "P", 660.0, 2, 3, 2.05), ("QQQ", "P", 590.0, 2, 22, 5.35),
]
STOCKS = [("AAPL", 300, 238.40), ("NVDA", 500, 172.35), ("MSFT", 100, 498.20)]


def _occ(under, exp, type_, strike):
    return f"{under:<6}{exp.replace('-', '')[2:]}{type_}{int(strike * 1000):08d}"


class DemoPositions:
    def get_account_snapshot(self):
        positions = []
        for sym, qty, avg in STOCKS:
            positions.append({
                "asset_type": "EQUITY", "symbol": sym, "long_quantity": qty, "short_quantity": 0, "average_price": avg,
                "tax_lot_long_price": avg, "tax_lot_short_price": None, "long_open_pl": (spot_of(sym) - avg) * qty,
                "short_open_pl": None, "maintenance_requirement": round(spot_of(sym) * qty * 0.25, 2),
                "underlying_symbol": None, "strike_price": None, "expiration_date": None, "option_type": None,
            })
        for under, type_, strike, qty, dte, prem in OPEN_SHORTS:
            exp = _friday(dte - 3).isoformat() if dte > 3 else _day(dte)
            positions.append({
                "asset_type": "OPTION", "symbol": _occ(under, exp, type_, strike), "long_quantity": 0, "short_quantity": qty,
                "average_price": prem, "tax_lot_long_price": None, "tax_lot_short_price": prem, "long_open_pl": None,
                "short_open_pl": None, "maintenance_requirement": round(strike * 100 * qty * 0.2, 2) if type_ == "P" else 0.0,
                "underlying_symbol": under, "strike_price": strike, "expiration_date": exp, "option_type": type_,
            })
        return {
            "balances": {
                "margin_balance": 0.0, "cash_balance": 182_450.32, "mutual_fund_value": 0.0, "short_balance": 0.0,
                "liquidation_value": 412_318.55, "net_liquidity": 468_904.10, "maintenance_requirement": 96_412.00,
                "available_funds": 214_806.73,
            },
            "positions": positions,
        }

    def get_quotes(self, symbols):
        out = {}
        for s in symbols:
            if len(s) > 15:  # an option (OCC symbol)
                under, exp = s[:6].strip(), f"20{s[6:8]}-{s[8:10]}-{s[10:12]}"
                strike, is_call = int(s[13:]) / 1000, s[12] == "C"
                dte = max((date.fromisoformat(exp) - market_today()).days, 0)
                out[s] = round(bs(spot_of(under), strike, dte, iv_of(under), is_call)[0], 2)
            else:
                out[s] = spot_of(s)
        return out

    def list_accounts(self):
        return [
            {"id": "demo-a", "number": "DEMO00000112", "type": "MARGIN", "value": 468_904.10},
            {"id": "demo-b", "number": "DEMO00004785", "type": "MARGIN", "value": 121_560.00},
        ]


def _leg(day, effect, amount, price, strike, type_, under, exp, close_event=None):
    return {
        "date": day, "close_date": exp, "underlying_symbol": under, "expirationDate": exp, "strike_price": strike,
        "symbol": f"{under} {exp} {strike} {type_[0]}", "price": price, "amount": amount, "position_effect": effect,
        "option_type": type_, "type": "TRADE", "close_event": close_event,
        "total_amount": price * -amount * get_contract_multiplier(under),
        "open_price": price if effect == "OPENING" else 0.0, "close_price": price if effect == "CLOSING" else 0.0,
        "open_type": ("BTO" if amount > 0 else "STO") if effect == "OPENING" else None,
    }


def _option_legs():
    rng = random.Random(7)
    legs = []
    tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "IWM"]
    for week in range(1, 52):  # a year of weekly short puts and calls, closed
        for j in range(2):
            under = tickers[(week * 2 + j) % len(tickers)]
            type_ = "PUT" if (week + j) % 3 else "CALL"
            spot = spot_of(under) * (1 - week * 0.003)
            step = strike_step(spot)
            strike = round(spot * (0.96 if type_ == "PUT" else 1.04) / step) * step
            opened = _friday(-7 * week) - timedelta(days=4)
            exp = (opened + timedelta(days=4)).isoformat()
            qty = rng.choice([1, 2, 2, 3])
            prem = round(spot * iv_of(under) * 0.012 * rng.uniform(0.7, 1.3), 2)
            legs.append(_leg(opened.isoformat(), "OPENING", -qty, prem, strike, type_, under, exp))
            roll = rng.random()
            if roll < 0.62:
                legs.append(_leg(exp, "CLOSING", qty, 0.0, strike, type_, under, exp, "EXPIRATION"))
            elif roll < 0.9:
                legs.append(_leg((opened + timedelta(days=2)).isoformat(), "CLOSING", qty, round(prem * 0.45, 2), strike, type_, under, exp))
            else:
                legs.append(_leg((opened + timedelta(days=3)).isoformat(), "CLOSING", qty, round(prem * 2.6, 2), strike, type_, under, exp))
    for week in range(1, 26):  # /ES and /NQ short puts, closed
        under = "ES" if week % 2 else "NQ"
        spot = spot_of("/" + under) * (1 - week * 0.004)
        step = strike_step(spot)
        strike = round(spot * 0.97 / step) * step
        opened = _friday(-7 * week) - timedelta(days=3)
        exp = (opened + timedelta(days=3)).isoformat()
        prem = round(spot * 0.0022, 2)
        legs.append(_leg(opened.isoformat(), "OPENING", -2, prem, strike, "PUT", under, exp))
        legs.append(_leg(exp, "CLOSING", 2, 0.0, strike, "PUT", under, exp, "EXPIRATION"))
    # Open equity shorts (match the snapshot above) and open futures options.
    for under, t, strike, qty, dte, prem in OPEN_SHORTS:
        exp = _friday(dte - 3).isoformat() if dte > 3 else _day(dte)
        legs.append(_leg(_day(-5), "OPENING", -qty, prem, strike, "PUT" if t == "P" else "CALL", under, exp))
    es_exp, nq_exp = _day(1), _friday(5).isoformat()
    legs += [
        _leg(_day(-3), "OPENING", -2, 9.75, 7650.0, "PUT", "ES", es_exp),
        _leg(_day(-2), "OPENING", -1, 11.25, 7900.0, "CALL", "ES", es_exp),
        _leg(_day(-4), "OPENING", 1, 361.25, 29500.0, "PUT", "NQ", nq_exp),
        _leg(_day(-4), "OPENING", -2, 196.75, 29000.0, "PUT", "NQ", nq_exp),
    ]
    return legs


def _equity_legs():
    def fill(day, symbol, amount, price, asset_type="EQUITY", mult=1, effect=None):
        return {"date": day, "symbol": symbol, "asset_type": asset_type, "amount": amount, "price": price,
                "cost": -amount * price * mult, "position_effect": effect}
    legs = [
        fill(_day(-300), "AAPL", 300, 211.40, effect="OPENING"), fill(_day(-200), "AAPL", -300, 230.00, effect="CLOSING"),
        fill(_day(-180), "TSLA", 200, 395.00, effect="OPENING"), fill(_day(-120), "TSLA", -200, 371.50, effect="CLOSING"),
        fill(_day(-90), "AAPL", 300, 238.40, effect="OPENING"), fill(_day(-60), "NVDA", 500, 172.35, effect="OPENING"),
        fill(_day(-40), "MSFT", 100, 498.20, effect="OPENING"),
        fill(_day(-150), "/ESZ26:XCME", 1, 7210.00, "FUTURE", 50), fill(_day(-100), "/ESZ26:XCME", -1, 7395.25, "FUTURE", 50),
        fill(_day(-12), "/ESZ26:XCME", 1, 7688.50, "FUTURE", 50),
    ]
    return legs


def _income_fees():
    rows = []
    for m in range(12):
        d = (market_today().replace(day=15) - timedelta(days=30 * m)).isoformat()
        rows += [
            {"date": d, "kind": "INCOME", "category": "INTEREST", "description": "Credit interest", "amount": 412.18 - m * 6},
            {"date": d, "kind": "INCOME", "category": "DIVIDEND", "description": "AAPL dividend", "amount": 78.00},
            {"date": d, "kind": "FEE", "category": "COMMISSION", "description": "Options regulatory fees", "amount": -38.65 - m},
        ]
    return rows


class DemoTransactions:
    def __init__(self):
        self._options, self._equity, self._income = _option_legs(), _equity_legs(), _income_fees()

    @staticmethod
    def _within(rows, start, end):
        return [dict(r) for r in rows if start <= r["date"][:10] <= end]

    def fetch_raw_transactions(self, start_date, end_date):
        return []

    def fetch_option_legs(self, start_date, end_date):
        return self._within(self._options, start_date, end_date)

    def fetch_equity_future_legs(self, start_date, end_date):
        return self._within(self._equity, start_date, end_date)

    def fetch_income_and_fees(self, start_date, end_date):
        return self._within(self._income, start_date, end_date)

    def normalize_futures_symbol(self, symbol):
        if symbol and symbol.startswith("/"):
            return symbol.split(":")[0][1:-3]
        return symbol
