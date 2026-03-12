"""
╔══════════════════════════════════════════════════════════════════╗
║         OPTIONS PORTFOLIO OPTIMIZER — SPY / QQQ / IWM           ║
║         Strategy: Sell Puts & Calls | Cash-Constrained           ║
╚══════════════════════════════════════════════════════════════════╝

Pricing sourced live from Schwab MarketData API (get_chain).
Optimization: Maximize daily Theta collected subject to
              total margin exposure ≤ free_cash budget.
"""

import math
import sys
import json
import warnings
from dataclasses import dataclass, field
from typing import Literal, List, Optional
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import minimize

warnings.filterwarnings("ignore")


# ═════════════════════════════════════════════════════════════════════════════
# 1.  BLACK-SCHOLES ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def bs_price_and_greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: Literal["put", "call"]
) -> dict:
    """
    Returns Black-Scholes fair value + full Greeks for a European option.

    Parameters
    ----------
    S      : underlying spot price
    K      : strike price
    T      : time to expiry in years  (e.g. 30/365)
    r      : risk-free rate (decimal, e.g. 0.0525)
    sigma  : implied volatility (decimal, e.g. 0.18)
    option_type : 'put' or 'call'
    """
    if T <= 0:
        intrinsic = max(K - S, 0) if option_type == "put" else max(S - K, 0)
        return dict(price=intrinsic, delta=0.0, gamma=0.0,
                    theta=0.0, vega=0.0, rho=0.0, iv=sigma)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1, nd2   = norm.cdf(d1),  norm.cdf(d2)
    nnd1, nnd2 = norm.cdf(-d1), norm.cdf(-d2)
    pdf_d1     = norm.pdf(d1)
    disc       = math.exp(-r * T)

    if option_type == "call":
        price = S * nd1 - K * disc * nd2
        delta = nd1
        rho   = K * T * disc * nd2 / 100
    else:
        price = K * disc * nnd2 - S * nnd1
        delta = nd1 - 1
        rho   = -K * T * disc * nnd2 / 100

    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega  = S * pdf_d1 * math.sqrt(T) / 100          # per 1 % IV move
    theta = (
        (-S * pdf_d1 * sigma / (2 * math.sqrt(T))
         + (r * K * disc * nnd2 if option_type == "put"
            else -r * K * disc * nd2))
        / 365                                          # daily theta
    )

    return dict(price=max(price, 0.0), delta=delta, gamma=gamma,
                theta=theta, vega=vega, rho=rho, iv=sigma)


# ═════════════════════════════════════════════════════════════════════════════
# 2.  MARKET DATA  (Schwab API)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketSnapshot:
    ticker:  str
    spot:    float
    iv:      float          # ATM 30-day IV (decimal)
    fetched: str = field(default_factory=lambda: datetime.now(ET).strftime("%H:%M:%S ET"))


def fetch_market_data(tickers: List[str], risk_free_rate: float = 0.0525) -> dict[str, MarketSnapshot]:
    """
    Pull live spot prices and ATM IV for each ticker via Schwab's
    MarketData.get_chain().

    - spot  : OptionChainResponse.underlyingPrice
    - ATM IV: OptionChainResponse.volatility (chain-level, in %→decimal).
              Falls back to averaging individual contract IVs if chain-level
              is zero, then to hard-coded defaults if the API call fails.
    """
    from broker.market_data import MarketData
    from datetime import timedelta

    schwab    = MarketData()
    today     = datetime.now(ET).date()
    from_date = today.strftime("%Y-%m-%d")
    to_date   = (today + timedelta(days=35)).strftime("%Y-%m-%d")

    snapshots: dict[str, MarketSnapshot] = {}

    for ticker in tickers:
        print(f"  📡  Fetching {ticker} …", end=" ", flush=True)
        try:
            chain = schwab.get_chain(
                ticker,
                from_date=from_date,
                to_date=to_date,
                strike_count=5,
                contract_type="ALL",
            )
            if chain is None:
                raise ValueError("No chain returned from Schwab API")

            spot = chain.underlyingPrice

            # chain.volatility is reported in % (e.g. 18.0 → 18%)
            atm_iv = (chain.volatility / 100.0) if chain.volatility else 0.0

            # Fallback: average individual contract IVs when chain-level is 0
            if atm_iv <= 0:
                opt_ivs: List[float] = []
                for exp_map in filter(None, [chain.callExpDateMap, chain.putExpDateMap]):
                    for strikes in exp_map.values():
                        for options in strikes.values():
                            for opt in options:
                                if opt.volatility and opt.volatility > 0:
                                    opt_ivs.append(opt.volatility)
                if opt_ivs:
                    atm_iv = (sum(opt_ivs) / len(opt_ivs)) / 100.0

            snapshots[ticker] = MarketSnapshot(ticker=ticker, spot=spot, iv=atm_iv)
            print(f"spot={spot:.2f}  IV={atm_iv*100:.1f}%  ✓")

        except Exception as exc:
            print(f"⚠ WARNING: {exc}  — using fallback defaults")
            fallbacks = {"SPY": (540.0, 0.18), "QQQ": (460.0, 0.22), "IWM": (210.0, 0.24)}
            s, v = fallbacks.get(ticker, (100.0, 0.20))
            snapshots[ticker] = MarketSnapshot(ticker=ticker, spot=s, iv=v)

    return snapshots


# ═════════════════════════════════════════════════════════════════════════════
# 2b. PORTFOLIO STOCK HOLDINGS  (via PositionService)
# ═════════════════════════════════════════════════════════════════════════════

def fetch_portfolio_stocks(tickers: List[str]) -> dict[str, int]:
    """
    Fetch current share holdings for the given tickers from the brokerage account.

    Returns a dict mapping ticker → share count (positive = long, negative = short).
    Tickers not held will have a value of 0.
    """
    from service.position import PositionService

    try:
        svc = PositionService()
        stocks = svc.get_stocks()
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠  Could not fetch portfolio positions: {exc}")
        return {t: 0 for t in tickers}

    upper_tickers = {t.upper() for t in tickers}
    holdings: dict[str, int] = {t: 0 for t in tickers}

    for row in stocks:
        sym = row.get("symbol", "").upper()
        if sym in upper_tickers:
            # quantity is formatted as e.g. "1,000" — strip commas and cast
            raw = str(row.get("quantity", "0")).replace(",", "")
            try:
                holdings[sym] = int(float(raw))
            except ValueError:
                pass

    return holdings


def print_portfolio_stocks(holdings: dict[str, int], cost_basis: dict[str, float] | None = None) -> None:
    """Print a compact table of current stock holdings."""
    cb = cost_basis or {}
    print(f"\n  ┌─  CURRENT STOCK HOLDINGS  {'─'*54}┐")
    print(f"  │  {'Ticker':<10} {'Shares':>12}  {'Position':<20} {'Avg Cost':>10}            │")
    print(f"  │  {'──────':<10} {'──────':>12}  {'────────':<20} {'────────':>10}            │")
    for ticker, qty in holdings.items():
        pos_label = "Long" if qty > 0 else ("Short" if qty < 0 else "—")
        avg_cost_str = f"${cb[ticker]:,.2f}" if ticker in cb else "—"
        print(f"  │  {ticker:<10} {qty:>12,}  {pos_label:<20} {avg_cost_str:>10}            │")
    print(f"  └{'─'*81}┘")


def fetch_stock_cost_basis(tickers: List[str]) -> dict[str, float]:
    """
    Fetch the average cost basis (per share) for each ticker from the brokerage.

    Returns a dict mapping ticker → average price paid per share.
    Tickers not held will have a value of 0.0.
    """
    from service.position import PositionService

    try:
        svc = PositionService()
        stocks = svc.get_stocks()
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠  Could not fetch cost basis: {exc}")
        return {t: 0.0 for t in tickers}

    upper_tickers = {t.upper() for t in tickers}
    basis: dict[str, float] = {t: 0.0 for t in tickers}

    for row in stocks:
        sym = row.get("symbol", "").upper()
        if sym in upper_tickers:
            raw = str(row.get("trade_price", "0")).replace("$", "").replace(",", "")
            try:
                basis[sym] = float(raw)
            except ValueError:
                pass

    return basis


# ═════════════════════════════════════════════════════════════════════════════
# 3.  OPTION CANDIDATE UNIVERSE
# ═════════════════════════════════════════════════════════════════════════════

# Strikes as % from spot — dense near ATM where short-DTE premium lives,
# with wider steps further out for longer-dated candidates.
STRIKE_MONEYNESS = [
    -0.30, -0.20, -0.10,          # far OTM puts / far OTM calls
    -0.07, -0.05, -0.04, -0.03,   # moderate OTM puts
    -0.02, -0.01,                  # near OTM puts (critical for short DTE)
     0.01,  0.02,                  # near OTM calls
     0.03,  0.04,  0.05,  0.07,   # moderate OTM calls
     0.10,  0.20,  0.30,          # far OTM calls / far OTM puts
]


@dataclass
class OptionContract:
    ticker:     str
    spot:       float
    strike:     float
    dte:        int
    option_type: Literal["put", "call"]
    T:          float               # years
    bs:         dict = field(default_factory=dict)

    # computed after init
    margin_per_contract: float = 0.0
    ann_yield_pct:       float = 0.0
    theta_per_dollar:    float = 0.0
    label:               str = ""
    expiry_date:         str = ""   # calendar date of expiration (YYYY-MM-DD)

    def __post_init__(self):
        from datetime import timedelta
        otm_pct = (self.strike - self.spot) / self.spot * 100
        self.expiry_date = (datetime.now(ET).date() + timedelta(days=self.dte)).strftime("%Y-%m-%d")
        self.label = (
            f"{self.ticker} {self.option_type.upper()} "
            f"${self.strike:.0f} "
            f"{'OTM' if (self.option_type=='put' and otm_pct<0) or (self.option_type=='call' and otm_pct>0) else 'ITM'} "
            f"{self.expiry_date} ({self.dte}DTE)"
        )


def compute_margin(S: float, K: float, premium: float,
                   option_type: str) -> float:
    """
    Simplified Reg-T margin for a single short naked option (1 contract = 100 shares).

    Rule: greater of:
      (a) 20% of underlying value − OTM amount + premium received
      (b) 10% of strike price
    All values per contract (×100 multiplier).
    """
    otm = max(K - S, 0) if option_type == "put" else max(S - K, 0)
    method_a = (0.20 * S - otm + premium) * 100
    method_b = 0.10 * K * 100
    return max(method_a, method_b)


def build_universe(
    snapshots: dict[str, MarketSnapshot],
    risk_free_rate: float,
    type_filter: Literal["put", "call", "both"] = "both",
    max_dte: int = 45,
    min_premium: float = 0.10,
    min_delta: float = 0.05,   # minimum |delta| — filters out near-zero premium far-OTM
    max_delta: float = 0.50,   # maximum |delta| — must be < 0.50 to stay OTM
) -> List[OptionContract]:
    """Generate all candidate short OTM options across tickers, strikes, and expiries.

    OTM enforcement (strict):
      - Put  : strike must be strictly below spot (K < S)
      - Call : strike must be strictly above spot (K > S)
    Delta range (absolute value, both types):
      - Only contracts where min_delta <= |delta| <= max_delta are kept.
      - Setting max_delta < 0.50 guarantees OTM on a delta basis as well.
    """
    candidates: List[OptionContract] = []

    types = (["put", "call"] if type_filter == "both"
             else [type_filter])

    # Build DTE list from 1 up to max_dte so it always respects the config
    dte_list = list(range(1, max_dte + 1))

    for ticker, snap in snapshots.items():
        S, sigma = snap.spot, snap.iv
        for dte in dte_list:
            T = dte / 365.0
            for mono in STRIKE_MONEYNESS:
                K = round(S * (1 + mono))
                for opt_type in types:
                    # ── Strict OTM filter ────────────────────────────────────
                    # Put  OTM: strike must be below spot
                    # Call OTM: strike must be above spot
                    if opt_type == "put"  and K >= S: continue
                    if opt_type == "call" and K <= S: continue

                    bs = bs_price_and_greeks(S, K, T, risk_free_rate, sigma, opt_type)
                    if bs["price"] < min_premium:
                        continue

                    # ── Delta range filter (absolute value) ──────────────────
                    abs_delta = abs(bs["delta"])
                    if not (min_delta <= abs_delta <= max_delta):
                        continue

                    margin = compute_margin(S, K, bs["price"], opt_type)
                    if margin <= 0:
                        continue

                    # Annualised yield on margin
                    premium_per_contract = bs["price"] * 100
                    ann_yield = (premium_per_contract / margin) * (365 / dte) * 100

                    contract = OptionContract(
                        ticker=ticker, spot=S, strike=K,
                        dte=dte, option_type=opt_type, T=T, bs=bs,
                    )
                    contract.margin_per_contract = margin
                    contract.ann_yield_pct       = ann_yield
                    contract.theta_per_dollar    = abs(bs["theta"]) * 100 / margin

                    candidates.append(contract)

    return candidates


# ═════════════════════════════════════════════════════════════════════════════
# 4.  PORTFOLIO OPTIMISER
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    contract:          OptionContract
    contracts:         int
    total_premium:     float
    total_margin:      float
    total_theta:       float   # daily $ theta collected (positive = income)
    total_delta:       float
    covered_contracts: int = 0  # how many contracts are covered by held shares

@dataclass
class OptimizedPortfolio:
    positions:      List[Position]
    total_margin:   float
    total_premium:  float
    total_theta:    float
    total_delta:    float
    total_vega:     float
    total_gamma:    float
    cash_used_pct:  float
    free_cash:      float


def greedy_optimise(
    candidates:              List[OptionContract],
    free_cash:               float,
    max_contracts:           int          = 10,
    max_delta_abs:           float        = 100,   # max deviation from target_delta
    target_delta:            float        = 0.0,   # target portfolio delta (0 = delta neutral)
    max_vega:                float        = -1,    # -1 = no limit
    max_margin_pct:          float        = 1.0,   # max total margin as fraction of free_cash (e.g. 0.80 = 80%)
    max_ticker_margin_pct:   float        = 0.40,  # max margin for any single ticker as fraction of margin_budget
    holdings:                Optional[dict] = None, # {ticker: share_count} for covered-call margin relief
    max_naked_calls_per_ticker: int       = 10,    # max naked short call contracts per ticker across portfolio
    cost_basis:              Optional[dict] = None, # {ticker: avg_cost_per_share} — covered calls must not risk a loss
) -> OptimizedPortfolio:
    """
    Greedy allocation:
      1. Rank by theta_per_dollar (highest first)
      2. Fill greedily while margin budget, delta band, and concentration limits hold

    max_margin_pct caps how much of free_cash can be consumed as margin.
    target_delta / max_delta_abs: portfolio net delta is kept within
      [target_delta - max_delta_abs, target_delta + max_delta_abs].
      Set target_delta=0 and a small max_delta_abs for delta-neutral.
    max_ticker_margin_pct: no single ticker may use more than this fraction
      of the total margin budget (e.g. 0.40 = 40%).
    holdings: if provided, short CALL contracts for a ticker are treated as
      covered calls (margin = $0) up to floor(shares / 100) contracts.
    max_naked_calls_per_ticker: hard cap on naked short calls per ticker.
    cost_basis: if provided, a covered call is only considered if
      strike + premium >= cost_basis[ticker], so assignment never locks in
      a loss on the underlying shares.
    """
    margin_budget = free_cash * max(0.0, min(max_margin_pct, 1.0))

    # Covered-call slots per ticker: each 100 shares covers 1 contract
    _holdings = holdings or {}
    covered_slots: dict[str, int] = {
        t: max(0, qty // 100) for t, qty in _holdings.items() if qty > 0
    }
    covered_used: dict[str, int] = {t: 0 for t in covered_slots}

    # Track naked call contracts allocated per ticker
    naked_call_used: dict[str, int] = {}

    _cost_basis = cost_basis or {}

    # Per-ticker margin cap
    ticker_margin_cap = margin_budget * max(0.0, min(max_ticker_margin_pct, 1.0))
    ticker_margin_used: dict[str, float] = {}

    ranked = sorted(candidates, key=lambda c: c.theta_per_dollar, reverse=True)

    positions:   List[Position] = []
    used_margin  = 0.0
    port_delta   = 0.0

    for cand in ranked:
        # How many of these call contracts can be covered by held shares?
        if cand.option_type == "call":
            covered_avail = max(0, covered_slots.get(cand.ticker, 0)
                                   - covered_used.get(cand.ticker, 0))
        else:
            covered_avail = 0

        # Covered call loss-prevention: strike + premium must cover cost basis
        if cand.option_type == "call" and covered_avail > 0:
            cb = _cost_basis.get(cand.ticker, 0.0)
            if cb > 0 and (cand.strike + cand.bs["price"]) < cb:
                # This strike risks a loss on assignment — treat as naked only
                covered_avail = 0

        # Effective margin per contract (0 for covered, full for naked)
        # We'll compute the blended max-n separately below.
        naked_margin = cand.margin_per_contract

        # Maximum contracts we can afford (covered ones cost $0 in margin)
        remaining = margin_budget - used_margin
        # covered_avail contracts are free; the rest cost naked_margin each
        free_contracts = min(covered_avail, max_contracts)
        if naked_margin > 0:
            paid_capacity = int(remaining // naked_margin)
        else:
            paid_capacity = max_contracts
        n = min(free_contracts + paid_capacity, max_contracts)
        if n < 1:
            continue

        # Per-ticker margin cap — reduce n so this ticker stays within cap
        t_margin_used = ticker_margin_used.get(cand.ticker, 0.0)
        t_margin_remaining = ticker_margin_cap - t_margin_used
        if t_margin_remaining <= 0:
            if min(n, covered_avail) < 1:   # no covered slots left either
                continue
            n = min(n, covered_avail)       # only covered (zero-margin) contracts allowed
        elif naked_margin > 0:
            n_covered_cap = min(covered_avail, n)
            n_naked_cap   = min(n - n_covered_cap, int(t_margin_remaining // naked_margin))
            n = n_covered_cap + n_naked_cap
            if n < 1:
                continue

        # Delta guard — keep portfolio within [target_delta ± max_delta_abs]
        delta_add = cand.bs["delta"] * 100 * n
        if abs(port_delta + delta_add - target_delta) > max_delta_abs:
            # Find the largest n that keeps delta within the band
            best_n = 0
            for test_n in range(n, 0, -1):
                if abs(port_delta + cand.bs["delta"] * 100 * test_n - target_delta) <= max_delta_abs:
                    best_n = test_n
                    break
            if best_n < 1:
                continue
            n = best_n

        # Split into covered vs naked contracts
        n_covered = min(n, covered_avail)
        n_naked   = n - n_covered

        # Cap naked calls per ticker across the portfolio
        if cand.option_type == "call" and n_naked > 0:
            naked_used = naked_call_used.get(cand.ticker, 0)
            naked_allowed = max(0, max_naked_calls_per_ticker - naked_used)
            if naked_allowed == 0:
                # Only covered contracts are allowed
                n_naked = 0
                n       = n_covered
                if n < 1:
                    continue
            elif n_naked > naked_allowed:
                n_naked = naked_allowed
                n       = n_covered + n_naked

        # Verify naked portion fits margin budget
        if n_naked > 0 and n_naked * naked_margin > remaining:
            n_naked   = int(remaining // naked_margin)
            n         = n_covered + n_naked
            if n < 1:
                continue

        margin = n_naked * naked_margin  # covered portion adds $0 margin
        used_margin  += margin
        port_delta   += cand.bs["delta"] * 100 * n
        ticker_margin_used[cand.ticker] = ticker_margin_used.get(cand.ticker, 0.0) + margin
        if cand.ticker in covered_used:
            covered_used[cand.ticker] += n_covered
        if cand.option_type == "call" and n_naked > 0:
            naked_call_used[cand.ticker] = naked_call_used.get(cand.ticker, 0) + n_naked

        positions.append(Position(
            contract           = cand,
            contracts          = n,
            total_premium      = cand.bs["price"] * 100 * n,
            total_margin       = margin,
            total_theta        = abs(cand.bs["theta"]) * 100 * n,
            total_delta        = cand.bs["delta"] * 100 * n,
            covered_contracts  = n_covered,
        ))

    total_vega  = sum(p.contract.bs["vega"]  * 100 * p.contracts for p in positions)
    total_gamma = sum(p.contract.bs["gamma"] * 100 * p.contracts for p in positions)

    return OptimizedPortfolio(
        positions     = positions,
        total_margin  = used_margin,
        total_premium = sum(p.total_premium for p in positions),
        total_theta   = sum(p.total_theta   for p in positions),
        total_delta   = sum(p.total_delta   for p in positions),
        total_vega    = total_vega,
        total_gamma   = total_gamma,
        cash_used_pct = used_margin / free_cash * 100 if free_cash else 0,
        free_cash     = free_cash,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 5.  REPORTING
# ═════════════════════════════════════════════════════════════════════════════

HEADER = "═" * 82

def print_header():
    print(f"\n{HEADER}")
    print("  OPTIONS PORTFOLIO OPTIMIZER  ·  SPY / QQQ / IWM  ·  Short Puts & Calls")
    print(HEADER)

def print_market_data(snapshots: dict[str, MarketSnapshot]):
    print("\n┌─  MARKET SNAPSHOT  " + "─" * 61 + "┐")
    print(f"  {'TICKER':<8}  {'SPOT':>8}  {'ATM IV':>8}  {'FETCHED':>10}")
    print(f"  {'──────':<8}  {'────':>8}  {'──────':>8}  {'───────':>10}")
    for snap in snapshots.values():
        print(f"  {snap.ticker:<8}  {snap.spot:>8.2f}  {snap.iv*100:>7.1f}%  {snap.fetched:>10}")
    print("└" + "─" * 81 + "┘")

def print_scanner(candidates: List[OptionContract], top_n: int = 20):
    ranked = sorted(candidates, key=lambda c: c.ann_yield_pct, reverse=True)[:top_n]
    print(f"\n┌─  TOP {top_n} CANDIDATES BY ANNUALISED YIELD  " + "─" * 47 + "┐")
    print(f"  {'#':>2}  {'TICKER':<6} {'TYPE':<5} {'STRIKE':>7} {'EXPIRY':<12} {'DTE':>4} "
          f"{'PREMIUM':>8} {'MARGIN':>8} {'ANN YLD':>8} {'THETA/D':>8} {'DELTA':>7}")
    print(f"  {'──':>2}  {'──────':<6} {'────':<5} {'──────':>7} {'──────────':<12} {'───':>4} "
          f"{'───────':>8} {'──────':>8} {'───────':>8} {'───────':>8} {'─────':>7}")
    for i, c in enumerate(ranked, 1):
        print(
            f"  {i:>2}  {c.ticker:<6} {c.option_type.upper():<5} ${c.strike:>6.0f} "
            f"{c.expiry_date:<12} {c.dte:>4}  "
            f"${c.bs['price']:>6.2f}  ${c.margin_per_contract:>6.0f}  "
            f"{c.ann_yield_pct:>7.1f}%  "
            f"${abs(c.bs['theta'])*100:>6.2f}  "
            f"{c.bs['delta']:>+7.4f}"
        )
    print("└" + "─" * 91 + "┘")

def print_portfolio(pf: OptimizedPortfolio):
    print(f"\n{HEADER}")
    print("  OPTIMISED PORTFOLIO")
    print(HEADER)
    print(f"\n  Free Cash Budget : ${pf.free_cash:>12,.0f}")
    print(f"  Margin Used      : ${pf.total_margin:>12,.0f}  ({pf.cash_used_pct:.1f}% of budget)")
    print(f"  Cash Remaining   : ${pf.free_cash - pf.total_margin:>12,.0f}")
    print()

    if not pf.positions:
        print("  ⚠  No positions allocated. Relax constraints or increase free cash.\n")
        return

    print(f"  {'#':>2}  {'CONTRACT':<50} {'QTY':>4} {'PREMIUM':>9} {'MARGIN':>9} {'Θ/DAY':>8} {'DELTA':>8}")
    print(f"  {'──':>2}  {'────────':<50} {'───':>4} {'───────':>9} {'──────':>9} {'─────':>8} {'─────':>8}")

    for i, pos in enumerate(pf.positions, 1):
        c = pos.contract
        # Annotate covered calls
        coverage_tag = ""
        if c.option_type == "call" and pos.covered_contracts > 0:
            if pos.covered_contracts == pos.contracts:
                coverage_tag = " [COVERED]"
            else:
                coverage_tag = f" [{pos.covered_contracts}COV/{pos.contracts - pos.covered_contracts}NAKED]"
        label_str = c.label + coverage_tag
        print(
            f"  {i:>2}  {label_str:<60} {pos.contracts:>4}  "
            f"${pos.total_premium:>7,.0f}  ${pos.total_margin:>7,.0f}  "
            f"${pos.total_theta:>6.2f}  {pos.total_delta:>+8.1f}"
        )

    print(f"\n  {'':>56}{'─────────':>9}  {'────────':>8}  {'────────':>8}")
    print(
        f"  {'TOTALS':>56}  ${pf.total_premium:>7,.0f}  "
        f"${pf.total_theta:>6.2f}  {pf.total_delta:>+8.1f}"
    )

    # Summary Greeks box
    ann_theta = pf.total_theta * 365
    theta_on_margin = (pf.total_theta * 365 / pf.total_margin * 100) if pf.total_margin else 0

    print(f"\n  ┌─  PORTFOLIO GREEKS & METRICS  {'─'*49}┐")
    print(f"  │  Daily Theta Collected  : ${pf.total_theta:>9.2f}                              │")
    print(f"  │  Annual Theta (est.)    : ${ann_theta:>9,.0f}                              │")
    print(f"  │  Theta / Margin (ann.)  :  {theta_on_margin:>8.1f}%                              │")
    print(f"  │  Net Delta              :  {pf.total_delta:>+9.1f}                              │")
    print(f"  │  Net Vega (per 1% IV↑)  : ${pf.total_vega:>9.2f}                              │")
    print(f"  │  Net Gamma              :  {pf.total_gamma:>+9.4f}                              │")
    print(f"  └{'─'*81}┘")


def export_to_csv(pf: OptimizedPortfolio, path: str = "portfolio.csv"):
    rows = []
    for pos in pf.positions:
        c = pos.contract
        rows.append({
            "ticker":        c.ticker,
            "type":          c.option_type,
            "strike":        c.strike,
            "expiry_date":   c.expiry_date,
            "dte":           c.dte,
            "contracts":     pos.contracts,
            "premium":       round(c.bs["price"], 2),
            "total_premium": round(pos.total_premium, 2),
            "margin":        round(pos.total_margin, 2),
            "theta_daily":   round(pos.total_theta, 4),
            "delta":         round(pos.total_delta, 4),
            "iv_pct":        round(c.bs["iv"] * 100, 2),
            "ann_yield_pct": round(c.ann_yield_pct, 2),
        })
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f"\n  📄  Portfolio exported → {path}")
    return df


# ═════════════════════════════════════════════════════════════════════════════
# 6.  CONFIGURATION  ←  Edit these to customise your run
# ═════════════════════════════════════════════════════════════════════════════

CONFIG = {
    # ── Cash constraint ───────────────────────────────────────────────────────
    "free_cash":        1500_000,    # total margin budget in $
    "stock_margin_pct": 0.50,        # Reg-T initial margin for stock holdings (50%)

    # ── Tickers (subset of SPY / QQQ / IWM) ──────────────────────────────────
    "tickers":          ["SPY", "QQQ", "IWM"],

    # ── Option filters ────────────────────────────────────────────────────────
    "type_filter":      "both",     # "put" | "call" | "both"
    "max_dte":          5,         # maximum days-to-expiry
    "min_premium":      0.10,       # skip options below this price
    "min_delta":        0.25,       # minimum |delta|  (0.25 = 25Δ)
    "max_delta":        0.45,       # maximum |delta|  (< 0.50 keeps strictly OTM)

    # ── Allocation constraints ────────────────────────────────────────────────
    "max_contracts":             10,   # max contracts per single position
    "max_delta_abs":            100,   # max deviation from target_delta
    "target_delta":             0.0,   # target portfolio delta (0 = delta neutral)
    "max_margin_pct":          0.60,   # max total margin as % of free_cash
    "max_ticker_margin_pct":   0.40,   # max margin per ticker as fraction of total margin budget
    "max_naked_calls_per_ticker": 10,  # max naked short call contracts per ticker across portfolio

    # ── Market / rates ────────────────────────────────────────────────────────
    "risk_free_rate":   0.0525,     # 5.25 % — adjust to current Fed Funds

    # ── Output ────────────────────────────────────────────────────────────────
    "scanner_top_n":    20,
    "export_csv":       True,
    "csv_path":         "portfolio.csv",
}


# ═════════════════════════════════════════════════════════════════════════════
# 7.  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def run(cfg: dict = CONFIG):
    print_header()

    # ── 0. Existing portfolio stock positions ────────────────────────────────
    print("\n  Fetching portfolio stock holdings …")
    holdings   = fetch_portfolio_stocks(cfg["tickers"])
    cost_basis = fetch_stock_cost_basis(cfg["tickers"])
    print_portfolio_stocks(holdings, cost_basis)

    # ── 1. Live market data ──────────────────────────────────────────────────
    print("\n  Fetching live market data …")
    snapshots = fetch_market_data(cfg["tickers"], cfg["risk_free_rate"])
    print_market_data(snapshots)

    # ── 1b. Deduct stock margin (50% Reg-T) from free cash ──────────────────
    stock_margin_pct = cfg.get("stock_margin_pct", 0.50)
    stock_market_value = sum(
        holdings.get(t, 0) * snapshots[t].spot
        for t in snapshots
        if holdings.get(t, 0) > 0
    )
    stock_cost = stock_market_value * stock_margin_pct
    free_cash = cfg["free_cash"] - stock_cost
    if stock_market_value > 0:
        print(f"\n  ┌─  CASH ADJUSTMENT FOR STOCK HOLDINGS  {'─'*41}┐")
        print(f"  │  Original Free Cash  : ${cfg['free_cash']:>12,.0f}                              │")
        print(f"  │  Stock Market Value  : ${stock_market_value:>12,.0f}                              │")
        print(f"  │  Stock Margin ({stock_margin_pct*100:.0f}%)   : ${stock_cost:>12,.0f}                              │")
        print(f"  │  Adjusted Free Cash  : ${free_cash:>12,.0f}                              │")
        print(f"  └{'─'*81}┘")

    # ── 2. Build option universe ─────────────────────────────────────────────
    print("\n  Building option universe …")
    candidates = build_universe(
        snapshots        = snapshots,
        risk_free_rate   = cfg["risk_free_rate"],
        type_filter      = cfg["type_filter"],
        max_dte          = cfg["max_dte"],
        min_premium      = cfg["min_premium"],
        min_delta        = cfg.get("min_delta", 0.25),
        max_delta        = cfg.get("max_delta", 0.45),
    )
    print(f"  {len(candidates)} candidate contracts generated.")

    # ── 3. Scanner ───────────────────────────────────────────────────────────
    print_scanner(candidates, top_n=cfg["scanner_top_n"])

    # ── 4. Optimise ──────────────────────────────────────────────────────────
    print("\n  Running optimiser …")
    portfolio = greedy_optimise(
        candidates                 = candidates,
        free_cash                  = free_cash,
        max_contracts              = cfg["max_contracts"],
        max_delta_abs              = cfg.get("max_delta_abs", 100),
        target_delta               = cfg.get("target_delta", 0.0),
        max_margin_pct             = cfg.get("max_margin_pct", 0.6),
        max_ticker_margin_pct      = cfg.get("max_ticker_margin_pct", 0.40),
        holdings                   = holdings,
        max_naked_calls_per_ticker = cfg.get("max_naked_calls_per_ticker", 10),
        cost_basis                 = cost_basis,
    )
    print_portfolio(portfolio)

    # ── 5. Export ────────────────────────────────────────────────────────────
    if cfg["export_csv"] and portfolio.positions:
        df = export_to_csv(portfolio, cfg["csv_path"])

    print(f"\n{HEADER}\n")
    return portfolio


if __name__ == "__main__":
    # ── Optional: override config from command line (JSON) ───────────────────
    # Example:
    #   python options_optimizer.py '{"free_cash": 50000, "type_filter": "put"}'
    cfg = dict(CONFIG)
    if len(sys.argv) > 1:
        overrides = json.loads(sys.argv[1])
        cfg.update(overrides)
        print(f"  Config overrides applied: {overrides}")

    run(cfg)