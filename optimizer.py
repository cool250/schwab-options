"""
╔══════════════════════════════════════════════════════════════════╗
║         OPTIONS PORTFOLIO OPTIMIZER — SPY / QQQ / IWM           ║
║         Strategy: Sell Puts & Calls | Cash-Constrained           ║
╚══════════════════════════════════════════════════════════════════╝

Pricing sourced live from Schwab MarketData API (get_chain).
Optimization: Maximize daily Theta collected subject to
              total margin exposure ≤ free_cash budget.
"""

import sys
import json
import warnings
from dataclasses import dataclass, field
from typing import Literal, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

warnings.filterwarnings("ignore")


# ═════════════════════════════════════════════════════════════════════════════
# 1.  RISK-REWARD SCORING
# ═════════════════════════════════════════════════════════════════════════════

def risk_reward_score(
    theta_per_dollar:   float,
    abs_delta:          float,
    gamma:              float,
    dte:                int,
    dte_sweet_spot:     int   = 30,
    delta_risk_exp:     float = 2.0,
    gamma_risk_weight:  float = 5.0,
    dte_risk_weight:         float = 0.3,
) -> float:
    """
    Composite risk-adjusted score for a short option candidate.

    Components
    ──────────
    theta_per_dollar   Raw daily theta per $ of margin — the base reward.

    delta_penalty      Scales reward DOWN as |delta| approaches 0.50.
                       A 0.40-delta contract is heavily penalized vs 0.20-delta,
                       even if both collect similar nominal theta.
                         exponent=1 → linear:    Δ0.30 penalty = 0.40
                         exponent=2 → quadratic: Δ0.30 penalty = 0.16  ← default
                         exponent=3 → cubic:     Δ0.30 penalty = 0.064

    gamma_penalty      Scales reward DOWN for high gamma.
                       Short-DTE near-ATM options have the highest gamma —
                       their delta can swing violently on an adverse move.

    dte_factor         Mild preference for the theta sweet-spot (~30 DTE).
                       Very short DTE (high gamma risk) and very long DTE
                       (slow decay, capital tied up) are both mildly penalized.
    """
    # Guard: if theta_per_dollar is zero or negative, score is zero
    if theta_per_dollar <= 0:
        return 0.0

    # Delta penalty — quadratic decay toward zero as |delta| → 0.50
    delta_ratio = min(abs_delta / 0.50, 1.0)
    delta_pen   = (1.0 - delta_ratio) ** delta_risk_exp

    # Gamma penalty — diminishing returns for high-gamma contracts
    gamma_pen   = 1.0 / (1.0 + gamma_risk_weight * gamma * 100)

    # DTE factor — mild sweet-spot preference
    dte_factor  = 1.0 - dte_risk_weight * abs(dte - dte_sweet_spot) / max(dte_sweet_spot, 1)
    dte_factor  = max(0.5, min(1.0, dte_factor))

    return theta_per_dollar * delta_pen * gamma_pen * dte_factor

# ═════════════════════════════════════════════════════════════════════════════
# 3.  MARKET DATA  (Schwab API)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketSnapshot:
    ticker:    str
    spot:      float
    iv:        float          # ATM 30-day IV (decimal)
    fetched:   str  = field(default_factory=lambda: datetime.now(ET).strftime("%H:%M:%S ET"))

@dataclass
class OptionContract:
    ticker:      str
    spot:        float
    strike:      float
    dte:         int
    option_type: Literal["put", "call"]
    bs:          dict = field(default_factory=dict)

    # ── Computed metrics ─────────────────────────────────────────────────────
    margin_per_contract: float = 0.0
    ann_yield_pct:       float = 0.0
    theta_per_dollar:    float = 0.0
    rr_score:            float = 0.0   # risk-adjusted composite score
    label:               str   = ""
    expiry_date:         str   = ""   # YYYY-MM-DD

    # ── Live market data (from Schwab chain; zero / False when unavailable) ──
    has_live_data:   bool  = False
    bid:             float = 0.0
    ask:             float = 0.0
    mark:            float = 0.0   # mid-market price from exchange
    last:            float = 0.0
    bid_size:        int   = 0
    ask_size:        int   = 0
    volume:          int   = 0
    open_interest:   int   = 0
    live_iv:         float = 0.0   # contract-level IV, decimal (e.g. 0.18 = 18%)
    live_delta:      float = 0.0   # per share
    live_gamma:      float = 0.0   # per share
    live_theta:      float = 0.0   # per share per day (negative = decay)
    live_vega:       float = 0.0   # per share per 1% IV move
    live_rho:        float = 0.0   # per share
    intrinsic_value: float = 0.0
    extrinsic_value: float = 0.0
    time_value:      float = 0.0
    percent_change:  float = 0.0
    mark_change:     float = 0.0
    in_the_money:    bool  = False

    def __post_init__(self):
        from datetime import timedelta
        otm_pct = (self.strike - self.spot) / self.spot * 100
        # Compute a default expiry date from DTE; fetch_market_data overrides this
        # with the actual chain expiry string once chain data is available.
        self.expiry_date = (datetime.now(ET).date() + timedelta(days=self.dte)).strftime("%Y-%m-%d")
        self.label = (
            f"{self.ticker} {self.option_type.upper()} "
            f"${self.strike:.0f} "
            f"{'OTM' if (self.option_type=='put' and otm_pct<0) or (self.option_type=='call' and otm_pct>0) else 'ITM'} "
            f"{self.expiry_date} ({self.dte}DTE)"
        )


def fetch_market_data(
    tickers: List[str],
    chain_strike_count: int = 50,
) -> tuple[dict[str, MarketSnapshot], List["OptionContract"]]:
    """
    Pull live spot prices, ATM IV, and full option chain for each ticker via
    Schwab's MarketData.get_chain().

    Returns
    -------
    snapshots     : {ticker → MarketSnapshot}  (spot + ATM IV, used for display)
    raw_contracts : List[OptionContract] with all live market fields populated.
                    BS metrics and scoring are NOT yet computed — that happens in build_universe().
    """
    from broker.market_data import MarketData
    from datetime import timedelta

    schwab    = MarketData()
    today     = datetime.now(ET).date()
    from_date = today.strftime("%Y-%m-%d")
    to_date   = (today + timedelta(days=35)).strftime("%Y-%m-%d")

    snapshots:     dict[str, MarketSnapshot] = {}
    raw_contracts: List[OptionContract]      = []

    for ticker in tickers:
        print(f"  📡  Fetching {ticker} …", end=" ", flush=True)
        try:
            chain = schwab.get_chain(
                ticker,
                from_date=from_date,
                to_date=to_date,
                strike_count=chain_strike_count,
                contract_type="ALL",
            )
            if chain is None:
                raise ValueError("No chain returned from Schwab API")

            spot = chain.underlyingPrice

            # chain.volatility is reported in % (e.g. 18.0 → 18%)
            atm_iv = (chain.volatility / 100.0) if chain.volatility else 0.0

            # ── Build OptionContract objects directly from chain data ─────────
            ticker_contracts = 0
            for _type, exp_map in [("call", chain.callExpDateMap), ("put", chain.putExpDateMap)]:
                if not exp_map:
                    continue
                for exp_key, strikes in exp_map.items():
                    # exp_key: "2026-03-20:5"  — date:DTE
                    parts = exp_key.split(":")
                    expiry_date_str = parts[0]
                    try:
                        dte = int(parts[1]) if len(parts) > 1 else 0
                    except ValueError:
                        continue
                    if dte <= 0:
                        continue

                    for strike_str, options in strikes.items():
                        try:
                            strike = round(float(strike_str))
                        except ValueError:
                            continue
                        for opt_detail in options:
                            contract = OptionContract(
                                ticker=ticker,
                                spot=spot,
                                strike=strike,
                                dte=dte,
                                option_type=_type,
                                bs={},
                            )
                            # Override __post_init__ computed expiry with the actual chain date
                            contract.expiry_date = expiry_date_str
                            otm_pct = (strike - spot) / spot * 100
                            contract.label = (
                                f"{ticker} {_type.upper()} "
                                f"${strike:.0f} "
                                f"{'OTM' if (_type=='put' and otm_pct<0) or (_type=='call' and otm_pct>0) else 'ITM'} "
                                f"{expiry_date_str} ({dte}DTE)"
                            )

                            # ── Populate live market fields ───────────────────
                            contract.has_live_data   = True
                            contract.bid             = opt_detail.bid
                            contract.ask             = opt_detail.ask
                            contract.mark            = opt_detail.mark
                            contract.last            = opt_detail.last
                            contract.bid_size        = opt_detail.bidSize
                            contract.ask_size        = opt_detail.askSize
                            contract.volume          = opt_detail.totalVolume
                            contract.open_interest   = opt_detail.openInterest
                            contract.live_iv         = (opt_detail.volatility / 100.0
                                                        if opt_detail.volatility and opt_detail.volatility > 0
                                                        else 0.0)
                            contract.live_delta      = opt_detail.delta
                            contract.live_gamma      = opt_detail.gamma
                            contract.live_theta      = opt_detail.theta
                            contract.live_vega       = opt_detail.vega
                            contract.live_rho        = opt_detail.rho
                            contract.intrinsic_value = opt_detail.intrinsicValue
                            contract.extrinsic_value = opt_detail.extrinsicValue
                            contract.time_value      = opt_detail.timeValue
                            contract.percent_change  = opt_detail.percentChange
                            contract.mark_change     = opt_detail.markChange
                            contract.in_the_money    = opt_detail.inTheMoney

                            raw_contracts.append(contract)
                            ticker_contracts += 1

            # Fallback: average individual contract IVs when chain-level is 0
            if atm_iv <= 0:
                opt_ivs = [c.live_iv for c in raw_contracts
                           if c.ticker == ticker and c.live_iv > 0]
                if opt_ivs:
                    atm_iv = sum(opt_ivs) / len(opt_ivs)

            snapshots[ticker] = MarketSnapshot(ticker=ticker, spot=spot, iv=atm_iv)
            print(f"spot={spot:.2f}  IV={atm_iv*100:.1f}%  {ticker_contracts} contracts  ✓")

        except Exception as exc:
            print(f"⚠ WARNING: {exc}  — using fallback defaults")
            fallbacks = {"SPY": (540.0, 0.18), "QQQ": (460.0, 0.22), "IWM": (210.0, 0.24)}
            s, v = fallbacks.get(ticker, (100.0, 0.20))
            snapshots[ticker] = MarketSnapshot(ticker=ticker, spot=s, iv=v)

    return snapshots, raw_contracts


# ═════════════════════════════════════════════════════════════════════════════
# 3b. PORTFOLIO STOCK HOLDINGS  (via PositionService)
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


def fetch_portfolio_options(tickers: List[str]) -> List[dict]:
    """
    Fetch current short/long option positions for the given tickers.

    Returns a flat list of dicts, one per position, with keys:
      ticker, symbol, option_type, strike_price, expiration_date,
      quantity, trade_price, total_value, current_price.
    """
    from service.position import PositionService

    try:
        svc = PositionService()
        puts, calls = svc.get_option_positions_details()
    except Exception as exc:
        print(f"  ⚠  Could not fetch option positions: {exc}")
        return []

    upper_tickers = {t.upper() for t in tickers}
    results = []
    for opt_type, positions in (("put", puts), ("call", calls)):
        for pos in positions:
            if pos.get("ticker", "").upper() in upper_tickers:
                results.append({**pos, "option_type": opt_type})
    return results


def print_portfolio_options(option_positions: List[dict]) -> None:
    """Print a compact table of current option positions."""
    if not option_positions:
        print(f"\n  ┌─  CURRENT OPTION POSITIONS  {'─'*63}┐")
        print(f"  │  No option positions found.{' '*61}│")
        print(f"  └{'─'*89}┘")
        return

    print(f"\n  ┌─  CURRENT OPTION POSITIONS  {'─'*63}┐")
    print(f"  │  {'Ticker':<7} {'Type':<5} {'Strike':>8} {'Expiry':<12} {'Qty':>6} {'Avg Cost':>10} {'Curr':>10} {'Delta':>7} {'Total Δ':>9}  │")
    print(f"  │  {'─'*6:<7} {'─'*4:<5} {'─'*6:>8} {'─'*10:<12} {'─'*5:>6} {'─'*8:>10} {'─'*8:>10} {'─'*5:>7} {'─'*7:>9}  │")
    grand_total_delta = 0.0
    for p in option_positions:
        delta = p.get("delta")
        raw_qty = str(p.get("quantity", "0")).replace(",", "")
        try:
            qty = float(raw_qty)
        except ValueError:
            qty = 0.0
        if delta is not None:
            total_delta = delta * 100 * qty
            grand_total_delta += total_delta
            delta_str       = f"{delta:>+7.4f}"
            total_delta_str = f"{total_delta:>+9.1f}"
        else:
            delta_str       = "      —"
            total_delta_str = "        —"
        print(
            f"  │  {p.get('ticker',''):<7} {p.get('option_type','').upper():<5} "
            f"{p.get('strike_price',''):>8} {p.get('expiration_date',''):<12} "
            f"{p.get('quantity',''):>6} {p.get('trade_price',''):>10} "
            f"{p.get('current_price',''):>10} {delta_str} {total_delta_str}  │"
        )
    print(f"  │  {'─'*87}│")
    print(f"  │  {'TOTAL DELTA':>80} {grand_total_delta:>+9.1f}  │")
    print(f"  └{'─'*89}┘")


def enrich_option_positions_with_delta(
    option_positions: List[dict],
    raw_contracts:    List["OptionContract"],
) -> None:
    """
    In-place: match each option position to its live delta from the fetched chain.

    Matching key: (ticker, option_type, round(strike), expiry YYYY-MM-DD).
    The position service stores expiry as MM-DD-YY; we convert it here.
    """
    # Build lookup from chain data
    chain_delta: dict[tuple, float] = {}
    for c in raw_contracts:
        key = (c.ticker.upper(), c.option_type, int(round(c.strike)), c.expiry_date)
        chain_delta[key] = c.live_delta

    for pos in option_positions:
        # parse_option_symbol returns expiry as "YY-MM-DD" (from OCC YYMMDD symbol)
        raw_exp = pos.get("expiration_date", "")   # e.g. "26-03-20"
        try:
            yy, mm, dd = raw_exp.split("-")
            expiry_norm = f"20{yy}-{mm}-{dd}"
        except ValueError:
            expiry_norm = raw_exp

        # Strip "$" and commas from strike_price
        raw_strike = str(pos.get("strike_price", "0")).replace("$", "").replace(",", "")
        try:
            strike = int(round(float(raw_strike)))
        except ValueError:
            continue

        ticker     = pos.get("ticker", "").upper()
        opt_type   = pos.get("option_type", "").lower()
        key        = (ticker, opt_type, strike, expiry_norm)
        if key in chain_delta:
            pos["delta"] = chain_delta[key]


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
# 4.  OPTION CANDIDATE UNIVERSE
# ═════════════════════════════════════════════════════════════════════════════

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
    raw_contracts: List[OptionContract],
    type_filter: Literal["put", "call", "both"] = "both",
    max_dte: int = 45,
    min_premium: float = 0.10,
    min_delta: float = 0.05,   # minimum |delta| — filters out near-zero premium far-OTM
    max_delta: float = 0.50,   # maximum |delta| — must be < 0.50 to stay OTM
    delta_risk_exp:    float = 2.0,
    gamma_risk_weight: float = 5.0,
    dte_risk_weight:   float = 0.3,
    dte_sweet_spot:    int   = 30,
) -> List[OptionContract]:
    """Filter and score pre-populated OptionContract objects from fetch_market_data().

    For each contract the function:
      1. Applies type / DTE / OTM / delta / premium filters using live chain data.
      2. Computes margin, annualised yield, theta-per-dollar, and rr_score from
         live mark price, delta, gamma, and theta.

    OTM enforcement (strict):
      - Put  : strike must be strictly below spot (K < S)
      - Call : strike must be strictly above spot (K > S)
    Delta range (absolute value):
      - Only contracts where min_delta <= |delta| <= max_delta are kept.
    """
    candidates: List[OptionContract] = []
    types = (["put", "call"] if type_filter == "both" else [type_filter])

    for c in raw_contracts:
        # ── Type / DTE filter ─────────────────────────────────────────────────
        if c.option_type not in types:
            continue
        if c.dte < 1 or c.dte > max_dte:
            continue

        S, K = c.spot, c.strike

        # ── Strict OTM filter ────────────────────────────────────────────────
        if c.option_type == "put"  and K >= S: continue
        if c.option_type == "call" and K <= S: continue

        # ── Use live market data directly ─────────────────────────────────────
        price     = c.mark if c.mark > 0 else ((c.bid + c.ask) / 2 if c.ask > 0 else 0.0)
        abs_delta = abs(c.live_delta)

        if price < min_premium:
            continue

        # ── Delta range filter (absolute value) ──────────────────────────────
        if not (min_delta <= abs_delta <= max_delta):
            continue

        margin = compute_margin(S, K, price, c.option_type)
        if margin <= 0:
            continue

        # ── Derived metrics ───────────────────────────────────────────────────
        ann_yield        = (price * 100 / margin) * (365 / c.dte) * 100
        theta_per_dollar = abs(c.live_theta) * 100 / margin

        rr = risk_reward_score(
            theta_per_dollar  = theta_per_dollar,
            abs_delta         = abs_delta,
            gamma             = c.live_gamma,
            dte               = c.dte,
            delta_risk_exp    = delta_risk_exp,
            gamma_risk_weight = gamma_risk_weight,
            dte_sweet_spot    = dte_sweet_spot,
            dte_risk_weight   = dte_risk_weight,
        )

        c.bs = {
            "price": price,
            "delta": c.live_delta,
            "gamma": c.live_gamma,
            "theta": c.live_theta,
            "vega":  c.live_vega,
            "rho":   c.live_rho,
            "iv":    c.live_iv,
        }
        c.margin_per_contract = margin
        c.ann_yield_pct       = ann_yield
        c.theta_per_dollar    = theta_per_dollar
        c.rr_score            = rr

        candidates.append(c)

    return candidates


# ═════════════════════════════════════════════════════════════════════════════
# 5.  PORTFOLIO OPTIMISER
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
    positions:      List[Position]  # list of allocated positions
    total_margin:   float           # total Reg-T margin consumed across all positions ($)
    total_premium:  float           # total premium collected across all positions ($)
    total_theta:    float           # total daily theta income across all positions ($/day)
    total_vega:     float           # net vega exposure: $ change per +1% IV move
    total_gamma:    float           # net gamma: rate of delta change per $1 move in underlying
    cash_used_pct:  float           # total_margin as a percentage of free_cash budget
    free_cash:      float           # margin budget available for new trades (after stock margin deduction)
    initial_delta:  float           # portfolio delta BEFORE new trades (stocks + held options)
    total_delta:    float           # portfolio delta AFTER new trades (initial + new-trade delta)

def compute_initial_delta(
    holdings: dict[str, int],
    option_positions: list[dict],
    tickers: list[str],
) -> tuple[float, dict[str, float]]:
    """
    Compute the portfolio delta that already exists BEFORE new trades.

    Returns
    -------
    total_initial_delta  : float           — portfolio-level
    ticker_initial_delta : dict[str,float] — per-ticker breakdown
    """
    ticker_delta: dict[str, float] = {t: 0.0 for t in tickers}

    # Long stock contributes +100 delta per 100 shares
    for t, qty in holdings.items():
        if t in ticker_delta:
            ticker_delta[t] += float(qty)  # each share = 1 delta

    # Existing short options: qty is negative for short positions
    for pos in option_positions:
        t = pos.get("ticker", "").upper()
        if t not in ticker_delta:
            continue
        raw_qty = str(pos.get("quantity", "0")).replace(",", "")
        try:
            qty = float(raw_qty)          # negative = short
        except ValueError:
            continue
        # delta per share from the live price; fallback to 0
        live_delta = float(pos.get("delta", 0.0) or 0.0)
        ticker_delta[t] += live_delta * 100 * qty  # contract-level

    total_delta = sum(ticker_delta.values())
    return total_delta, ticker_delta

def greedy_optimise(
    candidates:              List[OptionContract],
    free_cash:               float,
    min_contracts:           int          = 5,     # skip a position if fewer than this many contracts can be filled
    max_contracts:           int          = 10,
    max_delta_abs:           float        = 500,   # max portfolio net delta band
    max_ticker_delta_abs:    float        = 250,   # max |net delta| allowed per individual ticker
    target_delta:            float        = 0.0,   # target portfolio delta (0 = delta neutral)
    max_margin_pct:          float        = 1.0,   # max total margin as fraction of free_cash
    max_ticker_margin_pct:   float        = 0.40,  # max margin for any single ticker as fraction of margin_budget
    holdings:                Optional[dict] = None, # {ticker: share_count} for covered-call margin relief
    max_naked_calls_per_ticker: int       = 10,    # max naked short call contracts per ticker across portfolio
    cost_basis:              Optional[dict] = None, # {ticker: avg_cost_per_share} — covered calls must not risk a loss
    initial_portfolio_delta: float = 0.0,                        # pre-existing delta from stocks + option holdings (used for reporting only)
    initial_ticker_delta: dict[str, float] | None = None,        # per-ticker breakdown of pre-existing delta (used for reporting only)
) -> OptimizedPortfolio:
    """
    Greedy allocation — rank by rr_score, fill while margin budget, delta band,
    and concentration limits hold.

    max_margin_pct       : cap on total margin as fraction of free_cash.
    target_delta / max_delta_abs : portfolio net delta kept within
                           [target_delta ± max_delta_abs].
    max_ticker_delta_abs : per-ticker net delta kept within ±max_ticker_delta_abs.
    max_ticker_margin_pct: no single ticker exceeds this fraction of margin budget.
    min_contracts        : skip any position that can only be filled below this many contracts.
    holdings             : {ticker: shares} — covered calls get $0 margin up to
                           floor(shares / 100) contracts.
    max_naked_calls_per_ticker: hard cap on naked short calls per ticker.
    cost_basis           : covered call only allowed if strike + premium ≥ cost_basis.
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

    # Per-ticker delta tracking (for net-neutral enforcement)
    # Track new-trade delta only — initial_portfolio_delta is used for reporting only
    portfolio_delta = 0.0
    ticker_delta_used: dict[str, float] = {}

    # Covered calls on held tickers are evaluated first — they cost $0 margin and
    # reduce the long-delta exposure of the stock holdings.
    # Within each group, candidates are still ranked by rr_score.
    def _rank_key(c: OptionContract):
        is_covered_call = (
            c.option_type == "call"
            and covered_slots.get(c.ticker, 0) > 0
        )
        return (0 if is_covered_call else 1, -c.rr_score)

    ranked = sorted(candidates, key=_rank_key)

    positions:   List[Position] = []
    used_margin  = 0.0

    for cand in ranked:
        d = cand.bs["delta"] * 100   # contract-level delta (per-share × 100)

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
        if n < min_contracts:
            continue

        # Per-ticker margin cap — reduce n so this ticker stays within cap
        t_margin_used = ticker_margin_used.get(cand.ticker, 0.0)
        t_margin_remaining = ticker_margin_cap - t_margin_used
        if t_margin_remaining <= 0:
            if min(n, covered_avail) < min_contracts:   # not enough covered slots
                continue
            n = min(n, covered_avail)       # only covered (zero-margin) contracts allowed
        elif naked_margin > 0:
            n_covered_cap = min(covered_avail, n)
            n_naked_cap   = min(n - n_covered_cap, int(t_margin_remaining // naked_margin))
            n = n_covered_cap + n_naked_cap
            if n < min_contracts:
                continue

        # Delta guard — keep portfolio within [target_delta ± max_delta_abs]
        delta_add = d * n
        if abs(portfolio_delta + delta_add - target_delta) > max_delta_abs:
            best_n = 0
            for test_n in range(n, min_contracts - 1, -1):
                if abs(portfolio_delta + d * test_n - target_delta) <= max_delta_abs:
                    best_n = test_n
                    break
            if best_n < min_contracts:
                continue
            n = best_n

        # Per-ticker delta guard — keep each ticker net delta within ±max_ticker_delta_abs
        ticker_delta = ticker_delta_used.get(cand.ticker, 0.0)
        ticker_delta_add = d * n
        if abs(ticker_delta + ticker_delta_add) > max_ticker_delta_abs:
            best_n_ticker = 0
            for test_n in range(n, min_contracts - 1, -1):
                if abs(ticker_delta + d * test_n) <= max_ticker_delta_abs:
                    best_n_ticker = test_n
                    break
            if best_n_ticker < min_contracts:
                continue
            n = best_n_ticker

        # Split into covered vs naked contracts
        n_covered = min(n, covered_avail)
        n_naked   = n - n_covered

        # Cap naked calls per ticker across the portfolio
        if cand.option_type == "call" and n_naked > 0:
            naked_used = naked_call_used.get(cand.ticker, 0)
            naked_allowed = max(0, max_naked_calls_per_ticker - naked_used)
            if naked_allowed == 0:
                n_naked = 0
                n       = n_covered
                if n < min_contracts:
                    continue
            elif n_naked > naked_allowed:
                n_naked = naked_allowed
                n       = n_covered + n_naked

        # Verify naked portion fits margin budget
        if n_naked > 0 and n_naked * naked_margin > remaining:
            n_naked   = int(remaining // naked_margin)
            n         = n_covered + n_naked
            if n < min_contracts:
                continue

        # ── Commit position: update all running totals ────────────────────
        margin = n_naked * naked_margin  # covered portion adds $0 margin
        used_margin                    += margin                             # total margin consumed
        portfolio_delta                += d * n                             # new-trade delta only
        ticker_delta_used[cand.ticker]  = ticker_delta_used.get(cand.ticker, 0.0) + d * n
        ticker_margin_used[cand.ticker] = ticker_margin_used.get(cand.ticker, 0.0) + margin
        if cand.ticker in covered_used:
            covered_used[cand.ticker] += n_covered   # mark shares as covering these contracts
        if cand.option_type == "call" and n_naked > 0:
            naked_call_used[cand.ticker] = naked_call_used.get(cand.ticker, 0) + n_naked

        positions.append(Position(
            contract           = cand,
            contracts          = n,
            total_premium      = cand.bs["price"] * 100 * n,
            total_margin       = margin,
            total_theta        = abs(cand.bs["theta"]) * 100 * n,
            total_delta        = d * n,
            covered_contracts  = n_covered,
        ))

    total_vega  = sum(p.contract.bs["vega"]  * 100 * p.contracts for p in positions)
    total_gamma = sum(p.contract.bs["gamma"] * 100 * p.contracts for p in positions)

    return OptimizedPortfolio(
        positions     = positions,
        total_margin  = used_margin,
        total_premium = sum(p.total_premium for p in positions),
        total_theta   = sum(p.total_theta   for p in positions),
        total_delta   = initial_portfolio_delta + portfolio_delta,  # net after trades
        total_vega    = total_vega,
        total_gamma   = total_gamma,
        cash_used_pct = used_margin / free_cash * 100 if free_cash else 0,
        free_cash     = free_cash,
        initial_delta = initial_portfolio_delta,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 6.  REPORTING
# ═════════════════════════════════════════════════════════════════════════════

HEADER = "═" * 82

def print_header():
    print(f"\n{HEADER}")
    print("  OPTIONS PORTFOLIO OPTIMIZER  ·  SPY / QQQ / IWM  ·  Short Puts & Calls")
    print(HEADER)

def print_current_delta(
    total_initial_delta: float,
    ticker_initial_delta: dict[str, float],
) -> None:
    """Print the current portfolio delta broken down by ticker."""
    print(f"\n  ┌─  CURRENT PORTFOLIO DELTA  {'─'*56}┐")
    print(f"  │  {'TICKER':<10}  {'NET DELTA':>12}  {'DIRECTION':<20}              │")
    print(f"  │  {'─'*10:<10}  {'─'*9:>12}  {'─'*9:<20}              │")
    for ticker, delta in ticker_initial_delta.items():
        direction = "▲ Long" if delta > 0 else ("▼ Short" if delta < 0 else "Neutral")
        print(f"  │  {ticker:<10}  {delta:>+12.1f}  {direction:<20}              │")
    print(f"  │  {'─'*10:<10}  {'─'*9:>12}                                    │")
    direction = "▲ Long" if total_initial_delta > 0 else ("▼ Short" if total_initial_delta < 0 else "Neutral")
    print(f"  │  {'TOTAL':<10}  {total_initial_delta:>+12.1f}  {direction:<20}              │")
    print(f"  └{'─'*81}┘")


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
    print(f"  │  Current Delta (before trades): {pf.initial_delta:>+9.1f}                              │")
    print(f"  │  New Trades Delta            :  {pf.total_delta - pf.initial_delta:>+9.1f}                              │")
    print(f"  │  Net Delta (after trades)    :  {pf.total_delta:>+9.1f}                              │")
    print(f"  │  {'─'*77}│")
    print(f"  │  Daily Theta Collected  : ${pf.total_theta:>9.2f}                              │")
    print(f"  │  Annual Theta (est.)    : ${ann_theta:>9,.0f}                              │")
    print(f"  │  Theta / Margin (ann.)  :  {theta_on_margin:>8.1f}%                              │")
    print(f"  │  Net Vega (per 1% IV↑)  : ${pf.total_vega:>9.2f}                              │")
    print(f"  │  Net Gamma              :  {pf.total_gamma:>+9.4f}                              │")
    print(f"  └{'─'*81}┘")


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
    "min_contracts":              5,   # skip a position if fewer than this many contracts can be filled
    "max_delta_abs":            500,   # max portfolio net delta band (≥ max_contracts × max_delta × 100)
    "max_ticker_delta_abs":     250,   # max |net delta| per individual ticker (must be ≥ min_contracts × max_delta × 100)
    "target_delta":             0.0,   # target portfolio delta (0 = delta neutral)
    "max_margin_pct":          0.60,   # max total margin as % of free_cash
    "max_ticker_margin_pct":   0.40,   # max margin per ticker as fraction of total margin budget
    "max_naked_calls_per_ticker": 10,  # max naked short call contracts per ticker across portfolio

    # ── Risk-reward scoring weights ───────────────────────────────────────────
    "delta_risk_exp":            2.0,  # exponent for delta penalty in rr_score (1=linear, 2=quadratic)
    "gamma_risk_weight":         5.0,  # weight for gamma penalty: 1 / (1 + w * gamma * 100)
    "dte_sweet_spot":              5,  # DTE at which dte_factor peaks (set to match max_dte for short-DTE focus)
    "dte_risk_weight":           0.3,  # how steeply rr_score decays away from the sweet-spot DTE

    # ── Market data ───────────────────────────────────────────────────────────
    "chain_strike_count": 50,       # strikes fetched per side from Schwab

    # ── Output ────────────────────────────────────────────────────────────────
    "scanner_top_n":    20,
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

    print("\n  Fetching current option positions …")
    option_positions = fetch_portfolio_options(cfg["tickers"])

    # ── 1. Live market data ──────────────────────────────────────────────────
    print("\n  Fetching live market data …")
    snapshots, raw_contracts = fetch_market_data(
        cfg["tickers"],
        chain_strike_count=cfg.get("chain_strike_count", 50),
    )
    print_market_data(snapshots)

    # Enrich existing option positions with live delta from the chain
    enrich_option_positions_with_delta(option_positions, raw_contracts)
    print_portfolio_options(option_positions)

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
        print(f"  │  Stock Margin ({stock_margin_pct*100:.0f}%)   : ${stock_cost:>12,.0f}    │")
        print(f"  │  Adjusted Free Cash  : ${free_cash:>12,.0f}                              │")
        print(f"  └{'─'*81}┘")

    # ── 2. Build option universe ─────────────────────────────────────────────
    print("\n  Building option universe …")
    candidates = build_universe(
        raw_contracts    = raw_contracts,
        type_filter      = cfg["type_filter"],
        max_dte          = cfg["max_dte"],
        min_premium      = cfg["min_premium"],
        min_delta        = cfg.get("min_delta", 0.25),
        max_delta        = cfg.get("max_delta", 0.45),
        delta_risk_exp    = cfg.get("delta_risk_exp", 2.0),
        gamma_risk_weight = cfg.get("gamma_risk_weight", 5.0),
        dte_sweet_spot    = cfg.get("dte_sweet_spot", 5),
        dte_risk_weight   = cfg.get("dte_risk_weight", 0.3),
    )
    print(f"  {len(candidates)} candidate contracts generated.")

    # ── 3. Scanner ───────────────────────────────────────────────────────────
    print_scanner(candidates, top_n=cfg["scanner_top_n"])

    # ── 3b. Current portfolio delta (stocks + held options, before any new trade) ──
    initial_portfolio_delta, initial_ticker_delta = compute_initial_delta(
        holdings         = holdings,
        option_positions = option_positions,
        tickers          = cfg["tickers"],
    )
    print_current_delta(initial_portfolio_delta, initial_ticker_delta)


    # ── 4. Optimise ──────────────────────────────────────────────────────────
    print("\n  Running optimiser …")
    portfolio = greedy_optimise(
        candidates                 = candidates,
        free_cash                  = free_cash,
        initial_portfolio_delta = initial_portfolio_delta,
        initial_ticker_delta    = initial_ticker_delta,
        min_contracts              = cfg.get("min_contracts", 5),
        max_contracts              = cfg.get("max_contracts", 10),
        max_delta_abs              = cfg.get("max_delta_abs", 100),
        max_ticker_delta_abs       = cfg.get("max_ticker_delta_abs", 50),
        target_delta               = cfg.get("target_delta", 0.0),
        max_margin_pct             = cfg.get("max_margin_pct", 0.6),
        max_ticker_margin_pct      = cfg.get("max_ticker_margin_pct", 0.40),
        holdings                   = holdings,
        max_naked_calls_per_ticker = cfg.get("max_naked_calls_per_ticker", 10),
        cost_basis                 = cost_basis,
    )
    print_portfolio(portfolio)
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