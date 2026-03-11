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
    fetched: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


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
    today     = date.today()
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
# 3.  OPTION CANDIDATE UNIVERSE
# ═════════════════════════════════════════════════════════════════════════════

# Strikes as % OTM from spot  (negative = OTM for puts, positive = OTM for calls)
STRIKE_MONEYNESS = [-0.3, -0.2, -0.1, 0.00,0.1, 0.2, 0.3]
EXPIRY_DTE       = [1,2,3,4,5]


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

    def __post_init__(self):
        otm_pct = (self.strike - self.spot) / self.spot * 100
        self.label = (
            f"{self.ticker} {self.option_type.upper()} "
            f"${self.strike:.0f} "
            f"{'OTM' if (self.option_type=='put' and otm_pct<0) or (self.option_type=='call' and otm_pct>0) else 'ITM'} "
            f"({self.dte}DTE)"
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
    max_dte: int = 60,
    min_premium: float = 0.10,
) -> List[OptionContract]:
    """Generate all candidate short options across tickers, strikes, and expiries."""
    candidates: List[OptionContract] = []

    types = (["put", "call"] if type_filter == "both"
             else [type_filter])

    for ticker, snap in snapshots.items():
        S, sigma = snap.spot, snap.iv
        for dte in EXPIRY_DTE:
            if dte > max_dte:
                continue
            T = dte / 365.0
            for mono in STRIKE_MONEYNESS:
                K = round(S * (1 + mono))
                for opt_type in types:
                    # Skip strikes that are deep ITM (rarely sold)
                    if opt_type == "put"  and mono >  0.05: continue
                    if opt_type == "call" and mono < -0.05: continue

                    bs = bs_price_and_greeks(S, K, T, risk_free_rate, sigma, opt_type)
                    if bs["price"] < min_premium:
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
    contract:       OptionContract
    contracts:      int
    total_premium:  float
    total_margin:   float
    total_theta:    float   # daily $ theta collected (positive = income)
    total_delta:    float

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
    candidates:     List[OptionContract],
    free_cash:      float,
    max_contracts:  int          = 10,
    max_delta_abs:  float        = 500,   # portfolio-level delta limit
    max_vega:       float        = -1,    # -1 = no limit
) -> OptimizedPortfolio:
    """
    Greedy allocation:
      1. Rank by theta_per_dollar (highest first)
      2. Fill greedily while margin budget and delta limit hold
    """
    ranked = sorted(candidates, key=lambda c: c.theta_per_dollar, reverse=True)

    positions:   List[Position] = []
    used_margin  = 0.0
    port_delta   = 0.0

    for cand in ranked:
        remaining    = free_cash - used_margin
        if remaining < cand.margin_per_contract:
            continue

        affordable   = int(remaining // cand.margin_per_contract)
        n            = min(affordable, max_contracts)
        if n < 1:
            continue

        # Delta guard — don't blow the limit
        delta_add = cand.bs["delta"] * 100 * n
        if abs(port_delta + delta_add) > max_delta_abs:
            # Try to fit fewer contracts
            for test_n in range(n - 1, 0, -1):
                if abs(port_delta + cand.bs["delta"] * 100 * test_n) <= max_delta_abs:
                    n = test_n
                    break
            else:
                continue

        margin  = cand.margin_per_contract * n
        used_margin  += margin
        port_delta   += cand.bs["delta"] * 100 * n

        positions.append(Position(
            contract      = cand,
            contracts     = n,
            total_premium = cand.bs["price"] * 100 * n,
            total_margin  = margin,
            total_theta   = abs(cand.bs["theta"]) * 100 * n,
            total_delta   = cand.bs["delta"] * 100 * n,
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
    print(f"\n┌─  TOP {top_n} CANDIDATES BY ANNUALISED YIELD  " + "─" * 37 + "┐")
    print(f"  {'#':>2}  {'TICKER':<6} {'TYPE':<5} {'STRIKE':>7} {'DTE':>4} "
          f"{'PREMIUM':>8} {'MARGIN':>8} {'ANN YLD':>8} {'THETA/D':>8} {'DELTA':>7}")
    print(f"  {'──':>2}  {'──────':<6} {'────':<5} {'──────':>7} {'───':>4} "
          f"{'───────':>8} {'──────':>8} {'───────':>8} {'───────':>8} {'─────':>7}")
    for i, c in enumerate(ranked, 1):
        print(
            f"  {i:>2}  {c.ticker:<6} {c.option_type.upper():<5} ${c.strike:>6.0f} "
            f"{c.dte:>4}  "
            f"${c.bs['price']:>6.2f}  ${c.margin_per_contract:>6.0f}  "
            f"{c.ann_yield_pct:>7.1f}%  "
            f"${abs(c.bs['theta'])*100:>6.2f}  "
            f"{c.bs['delta']:>+7.4f}"
        )
    print("└" + "─" * 81 + "┘")

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

    print(f"  {'#':>2}  {'CONTRACT':<42} {'QTY':>4} {'PREMIUM':>9} {'MARGIN':>9} {'Θ/DAY':>8} {'DELTA':>8}")
    print(f"  {'──':>2}  {'────────':<42} {'───':>4} {'───────':>9} {'──────':>9} {'─────':>8} {'─────':>8}")

    for i, pos in enumerate(pf.positions, 1):
        c = pos.contract
        print(
            f"  {i:>2}  {c.label:<42} {pos.contracts:>4}  "
            f"${pos.total_premium:>7,.0f}  ${pos.total_margin:>7,.0f}  "
            f"${pos.total_theta:>6.2f}  {pos.total_delta:>+8.1f}"
        )

    print(f"\n  {'':>48}{'─────────':>9}  {'────────':>8}  {'────────':>8}")
    print(
        f"  {'TOTALS':>48}  ${pf.total_premium:>7,.0f}  "
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
            "ticker":     c.ticker,
            "type":       c.option_type,
            "strike":     c.strike,
            "dte":        c.dte,
            "contracts":  pos.contracts,
            "premium":    round(c.bs["price"], 2),
            "total_premium": round(pos.total_premium, 2),
            "margin":     round(pos.total_margin, 2),
            "theta_daily": round(pos.total_theta, 4),
            "delta":      round(pos.total_delta, 4),
            "iv_pct":     round(c.bs["iv"] * 100, 2),
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
    "free_cash":        100_000,    # total margin budget in $

    # ── Tickers (subset of SPY / QQQ / IWM) ──────────────────────────────────
    "tickers":          ["SPY", "QQQ", "IWM"],

    # ── Option filters ────────────────────────────────────────────────────────
    "type_filter":      "both",     # "put" | "call" | "both"
    "max_dte":          45,         # maximum days-to-expiry
    "min_premium":      0.10,       # skip options below this price

    # ── Allocation constraints ────────────────────────────────────────────────
    "max_contracts":    10,         # max contracts per single position
    "max_delta_abs":    500,        # abs portfolio delta cap

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

    # ── 1. Live market data ──────────────────────────────────────────────────
    print("\n  Fetching live market data …")
    snapshots = fetch_market_data(cfg["tickers"], cfg["risk_free_rate"])
    print_market_data(snapshots)

    # ── 2. Build option universe ─────────────────────────────────────────────
    print("\n  Building option universe …")
    candidates = build_universe(
        snapshots        = snapshots,
        risk_free_rate   = cfg["risk_free_rate"],
        type_filter      = cfg["type_filter"],
        max_dte          = cfg["max_dte"],
        min_premium      = cfg["min_premium"],
    )
    print(f"  {len(candidates)} candidate contracts generated.")

    # ── 3. Scanner ───────────────────────────────────────────────────────────
    print_scanner(candidates, top_n=cfg["scanner_top_n"])

    # ── 4. Optimise ──────────────────────────────────────────────────────────
    print("\n  Running optimiser …")
    portfolio = greedy_optimise(
        candidates    = candidates,
        free_cash     = cfg["free_cash"],
        max_contracts = cfg["max_contracts"],
        max_delta_abs = cfg["max_delta_abs"],
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