"""
╔══════════════════════════════════════════════════════════════════╗
║         OPTIONS PORTFOLIO OPTIMIZER — SPY / QQQ / IWM           ║
║         Strategy: Sell Puts & Calls | Cash-Constrained           ║
╚══════════════════════════════════════════════════════════════════╝

Pricing sourced live from Schwab MarketData API (get_chain).
Optimization: Maximize daily Theta collected subject to
              total margin exposure ≤ free_cash budget.
              Delta-neutral targeting: greedy ranker interleaves puts
              and calls to keep net portfolio delta near target_delta.
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
    dte_risk_weight:    float = 0.3,
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
    if theta_per_dollar <= 0:
        return 0.0

    delta_ratio = min(abs_delta / 0.50, 1.0)
    delta_pen   = (1.0 - delta_ratio) ** delta_risk_exp

    gamma_pen   = 1.0 / (1.0 + gamma_risk_weight * gamma * 100)

    dte_factor  = 1.0 - dte_risk_weight * abs(dte - dte_sweet_spot) / max(dte_sweet_spot, 1)
    dte_factor  = max(0.5, min(1.0, dte_factor))

    return theta_per_dollar * delta_pen * gamma_pen * dte_factor


# ═════════════════════════════════════════════════════════════════════════════
# 2.  MARKET DATA  (Schwab API)
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
    mark:            float = 0.0
    last:            float = 0.0
    bid_size:        int   = 0
    ask_size:        int   = 0
    volume:          int   = 0
    open_interest:   int   = 0
    live_iv:         float = 0.0
    live_delta:      float = 0.0   # per share (negative for puts, positive for calls)
    live_gamma:      float = 0.0
    live_theta:      float = 0.0   # per share per day (negative = decay)
    live_vega:       float = 0.0
    live_rho:        float = 0.0
    intrinsic_value: float = 0.0
    extrinsic_value: float = 0.0
    time_value:      float = 0.0
    percent_change:  float = 0.0
    mark_change:     float = 0.0
    in_the_money:    bool  = False

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


def fetch_market_data(
    tickers: List[str],
    chain_strike_count: int = 50,
) -> tuple[dict[str, MarketSnapshot], List["OptionContract"]]:
    """
    Pull live spot prices, ATM IV, and full option chain for each ticker via
    Schwab's MarketData.get_chain().
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

            spot   = chain.underlyingPrice
            atm_iv = (chain.volatility / 100.0) if chain.volatility else 0.0

            ticker_contracts = 0
            for _type, exp_map in [("call", chain.callExpDateMap), ("put", chain.putExpDateMap)]:
                if not exp_map:
                    continue
                for exp_key, strikes in exp_map.items():
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
                                ticker=ticker, spot=spot, strike=strike,
                                dte=dte, option_type=_type, bs={},
                            )
                            contract.expiry_date = expiry_date_str
                            otm_pct = (strike - spot) / spot * 100
                            contract.label = (
                                f"{ticker} {_type.upper()} ${strike:.0f} "
                                f"{'OTM' if (_type=='put' and otm_pct<0) or (_type=='call' and otm_pct>0) else 'ITM'} "
                                f"{expiry_date_str} ({dte}DTE)"
                            )
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

            if atm_iv <= 0:
                opt_ivs = [c.live_iv for c in raw_contracts if c.ticker == ticker and c.live_iv > 0]
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
# 3.  PORTFOLIO STOCK & OPTION HOLDINGS  (via PositionService)
# ═════════════════════════════════════════════════════════════════════════════

def fetch_portfolio_stocks(tickers: List[str]) -> dict[str, int]:
    from service.position import PositionService
    try:
        svc    = PositionService()
        stocks = svc.get_stocks()
    except Exception as exc:
        print(f"  ⚠  Could not fetch portfolio positions: {exc}")
        return {t: 0 for t in tickers}

    upper_tickers = {t.upper() for t in tickers}
    holdings: dict[str, int] = {t: 0 for t in tickers}
    for row in stocks:
        sym = row.get("symbol", "").upper()
        if sym in upper_tickers:
            raw = str(row.get("quantity", "0")).replace(",", "")
            try:
                holdings[sym] = int(float(raw))
            except ValueError:
                pass
    return holdings


def fetch_stock_cost_basis(tickers: List[str]) -> dict[str, float]:
    from service.position import PositionService
    try:
        svc    = PositionService()
        stocks = svc.get_stocks()
    except Exception as exc:
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


def fetch_portfolio_options(tickers: List[str]) -> List[dict]:
    from service.position import PositionService
    try:
        svc        = PositionService()
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


def enrich_option_positions_with_delta(
    option_positions: List[dict],
    raw_contracts:    List[OptionContract],
) -> None:
    """
    In-place: match each open option position to its live delta from the fetched chain.

    Matching key: (ticker, option_type, round(strike), expiry YYYY-MM-DD).

    Expiry format normalisation
    ───────────────────────────
    PositionService returns expiry as "YY-MM-DD" (from OCC YYMMDD symbol).
    Chain data uses "YYYY-MM-DD".  Both formats are handled gracefully.
    """
    chain_delta: dict[tuple, float] = {}
    for c in raw_contracts:
        key = (c.ticker.upper(), c.option_type, int(round(c.strike)), c.expiry_date)
        chain_delta[key] = c.live_delta

    for pos in option_positions:
        raw_exp = pos.get("expiration_date", "")
        parts   = raw_exp.split("-")
        if len(parts) == 3 and len(parts[0]) == 2:
            expiry_norm = f"20{parts[0]}-{parts[1]}-{parts[2]}"
        elif len(parts) == 3 and len(parts[0]) == 4:
            expiry_norm = raw_exp   # already YYYY-MM-DD
        else:
            expiry_norm = raw_exp   # best effort

        raw_strike = str(pos.get("strike_price", "0")).replace("$", "").replace(",", "")
        try:
            strike = int(round(float(raw_strike)))
        except ValueError:
            continue

        ticker   = pos.get("ticker", "").upper()
        opt_type = pos.get("option_type", "").lower()
        key      = (ticker, opt_type, strike, expiry_norm)
        if key in chain_delta:
            pos["delta"] = chain_delta[key]


# ═════════════════════════════════════════════════════════════════════════════
# 4.  PRINTING HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def print_portfolio_stocks(holdings: dict[str, int], cost_basis: dict[str, float] | None = None) -> None:
    cb = cost_basis or {}
    print(f"\n  ┌─  CURRENT STOCK HOLDINGS  {'─'*54}┐")
    print(f"  │  {'Ticker':<10} {'Shares':>12}  {'Position':<20} {'Avg Cost':>10}            │")
    print(f"  │  {'──────':<10} {'──────':>12}  {'────────':<20} {'────────':>10}            │")
    for ticker, qty in holdings.items():
        pos_label    = "Long" if qty > 0 else ("Short" if qty < 0 else "—")
        avg_cost_str = f"${cb[ticker]:,.2f}" if ticker in cb else "—"
        print(f"  │  {ticker:<10} {qty:>12,}  {pos_label:<20} {avg_cost_str:>10}            │")
    print(f"  └{'─'*81}┘")


def print_portfolio_options(option_positions: List[dict]) -> None:
    if not option_positions:
        print(f"\n  ┌─  CURRENT OPTION POSITIONS  {'─'*63}┐")
        print(f"  │  No option positions found.{' '*61}│")
        print(f"  └{'─'*89}┘")
        return

    print(f"\n  ┌─  CURRENT OPTION POSITIONS  {'─'*63}┐")
    print(f"  │  {'Ticker':<7} {'Type':<5} {'Strike':>8} {'Expiry':<12} {'Qty':>6} "
          f"{'Avg Cost':>10} {'Curr':>10} {'Delta':>7} {'Total Δ':>9}  │")
    print(f"  │  {'─'*6:<7} {'─'*4:<5} {'─'*6:>8} {'─'*10:<12} {'─'*5:>6} "
          f"{'─'*8:>10} {'─'*8:>10} {'─'*5:>7} {'─'*7:>9}  │")
    grand_total_delta = 0.0
    for p in option_positions:
        delta   = p.get("delta")
        raw_qty = str(p.get("quantity", "0")).replace(",", "")
        try:
            qty = float(raw_qty)
        except ValueError:
            qty = 0.0
        if delta is not None:
            # Short position delta: Schwab qty is positive for shorts, so negate chain delta
            # to get actual portfolio delta contribution (short put → positive delta)
            total_delta        = -(delta * 100 * qty)
            grand_total_delta += total_delta
            delta_str          = f"{delta:>+7.4f}"
            total_delta_str    = f"{total_delta:>+9.1f}"
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


# ═════════════════════════════════════════════════════════════════════════════
# 5.  OPTION CANDIDATE UNIVERSE
# ═════════════════════════════════════════════════════════════════════════════

def compute_margin(S: float, K: float, premium: float, option_type: str) -> float:
    """
    Simplified Reg-T margin for a single short naked option (1 contract = 100 shares).

    Rule: greater of:
      (a) 20% of underlying value − OTM amount + premium received
      (b) 10% of strike price

    OTM amount:
      Put  : max(S − K, 0)   — how far strike is below spot
      Call : max(K − S, 0)   — how far strike is above spot
    """
    otm      = max(S - K, 0) if option_type == "put" else max(K - S, 0)
    method_a = (0.20 * S - otm + premium) * 100
    method_b = 0.10 * K * 100
    return max(method_a, method_b)


def build_universe(
    raw_contracts:    List[OptionContract],
    type_filter:      Literal["put", "call", "both"] = "both",
    max_dte:          int   = 45,
    min_premium:      float = 0.10,
    min_delta:        float = 0.05,
    max_delta:        float = 0.50,
    delta_risk_exp:   float = 2.0,
    gamma_risk_weight:float = 5.0,
    dte_risk_weight:  float = 0.3,
    dte_sweet_spot:   int   = 30,
) -> List[OptionContract]:
    """
    Filter and score OptionContract objects from fetch_market_data().

    OTM enforcement (strict):
      - Put  : strike must be strictly below spot (K < S)
      - Call : strike must be strictly above spot (K > S)
    Delta range (absolute value):
      - Only contracts where min_delta ≤ |delta| ≤ max_delta are kept.
    """
    candidates: List[OptionContract] = []
    types = ["put", "call"] if type_filter == "both" else [type_filter]

    for c in raw_contracts:
        if c.option_type not in types:
            continue
        if c.dte < 1 or c.dte > max_dte:
            continue

        S, K = c.spot, c.strike

        if c.option_type == "put"  and K >= S: continue
        if c.option_type == "call" and K <= S: continue

        price     = c.mark if c.mark > 0 else ((c.bid + c.ask) / 2 if c.ask > 0 else 0.0)
        abs_delta = abs(c.live_delta)

        if price < min_premium:
            continue
        if not (min_delta <= abs_delta <= max_delta):
            continue

        margin = compute_margin(S, K, price, c.option_type)
        if margin <= 0:
            continue

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
# 6.  DELTA ACCOUNTING
# ═════════════════════════════════════════════════════════════════════════════

def contract_delta_actual(chain_delta_per_share: float) -> float:
    """
    Convert a Schwab chain delta (per share, long-option convention) into the
    actual portfolio delta contribution of ONE short contract.

    Schwab reports delta from the LONG option perspective:
      - Long put  → negative delta  (e.g. −0.30)
      - Long call → positive delta  (e.g. +0.35)

    For a SHORT position we flip the sign and scale by 100 shares:
      - Short put  → +30 delta  (profits when underlying rises — long delta)
      - Short call → −35 delta  (profits when underlying falls — short delta)
    """
    return -(chain_delta_per_share * 100)


def compute_initial_delta(
    holdings:         dict[str, int],
    option_positions: list[dict],
    tickers:          list[str],
) -> tuple[float, dict[str, float]]:
    """
    Compute portfolio delta BEFORE any new trades.

    Sign conventions
    ────────────────
    Stocks  : long shares → positive delta (1 delta per share)
    Options : uses contract_delta_actual() above.
              Schwab PositionService returns qty as a POSITIVE integer for
              short positions (direction is implied by account type).
              Therefore short put  → -(neg_delta × 100 × pos_qty) → positive
                          short call → -(pos_delta × 100 × pos_qty) → negative

    ⚠  If your PositionService returns NEGATIVE qty for short positions,
       remove the negation in contract_delta_actual and use: live_delta * 100 * qty.
       Run a quick print(option_positions) to verify before trusting these numbers.

    Returns
    ───────
    total_initial_delta  : float            — portfolio-level
    ticker_initial_delta : dict[str, float] — per-ticker breakdown
    """
    ticker_delta: dict[str, float] = {t: 0.0 for t in tickers}

    # Long stock: 1 delta per share
    for t, qty in holdings.items():
        if t in ticker_delta:
            ticker_delta[t] += float(qty)

    # Existing option positions
    for pos in option_positions:
        t = pos.get("ticker", "").upper()
        if t not in ticker_delta:
            continue
        raw_qty = str(pos.get("quantity", "0")).replace(",", "")
        try:
            qty = float(raw_qty)   # positive = short (Schwab PositionService convention)
        except ValueError:
            continue

        live_delta = float(pos.get("delta", 0.0) or 0.0)
        if live_delta == 0.0:
            continue  # skip unenriched positions rather than silently add zero

        # contract_delta_actual flips sign for short positions
        ticker_delta[t] += contract_delta_actual(live_delta) * qty

    total_delta = sum(ticker_delta.values())
    return total_delta, ticker_delta


# ═════════════════════════════════════════════════════════════════════════════
# 7.  PORTFOLIO OPTIMISER
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    contract:          OptionContract
    contracts:         int
    total_premium:     float
    total_margin:      float
    total_theta:       float   # daily $ theta income (positive = income)
    total_delta:       float   # actual portfolio delta contribution (short-adjusted)
    covered_contracts: int = 0


@dataclass
class OptimizedPortfolio:
    positions:     List[Position]
    total_margin:  float   # total Reg-T margin consumed ($)
    total_premium: float   # total premium collected ($)
    total_theta:   float   # total daily theta income ($/day)
    total_vega:    float   # net vega: $ change per +1% IV move
    total_gamma:   float   # net gamma: delta change per $1 underlying move
    cash_used_pct: float   # total_margin as % of free_cash budget
    free_cash:     float   # margin budget for new trades
    initial_delta: float   # portfolio delta BEFORE new trades (stocks + held options)
    total_delta:   float   # portfolio delta AFTER new trades (initial + new-trade delta)


def greedy_optimise(
    candidates:               List[OptionContract],
    free_cash:                float,
    min_contracts:            int           = 5,
    max_contracts:            int           = 10,
    max_delta_abs:            float         = 500,   # max |portfolio net delta| from target
    max_ticker_delta_abs:     float         = 250,   # max |net delta| per ticker
    target_delta:             float         = 0.0,   # 0 = delta-neutral
    max_margin_pct:           float         = 1.0,
    max_ticker_margin_pct:    float         = 0.40,
    holdings:                 Optional[dict]= None,
    max_naked_calls_per_ticker: int         = 10,
    cost_basis:               Optional[dict]= None,
    initial_portfolio_delta:  float         = 0.0,
    initial_ticker_delta:     dict[str, float] | None = None,
    resort_every:             int           = 3,     # re-sort candidates every N commits for adaptive delta steering
) -> OptimizedPortfolio:
    """
    Greedy allocation — rank by delta-benefit then rr_score.

    Delta-neutral design
    ────────────────────
    portfolio_delta and ticker_delta_used are SEEDED from initial_portfolio_delta /
    initial_ticker_delta so the guards reflect the real starting exposure
    (stocks + existing options), not zero.

    The ranking key re-evaluates every `resort_every` commits so that as the
    portfolio approaches target_delta, the ranker steers toward the opposite side
    (e.g. once long-heavy from puts, calls float to the top).

    Delta guard (portfolio + per-ticker)
    ─────────────────────────────────────
    Before committing n contracts, the optimizer checks:
      |portfolio_delta + d_actual×n − target_delta| ≤ max_delta_abs
    If violated, it walks n down to the largest feasible count ≥ min_contracts.
    Same logic applied per-ticker with max_ticker_delta_abs.
    """
    margin_budget      = free_cash * max(0.0, min(max_margin_pct, 1.0))
    ticker_margin_cap  = margin_budget * max(0.0, min(max_ticker_margin_pct, 1.0))

    # Covered-call slots
    _holdings     = holdings or {}
    covered_slots: dict[str, int] = {t: max(0, qty // 100) for t, qty in _holdings.items() if qty > 0}
    covered_used:  dict[str, int] = {t: 0 for t in covered_slots}

    _cost_basis        = cost_basis or {}
    naked_call_used:   dict[str, int]   = {}
    ticker_margin_used:dict[str, float] = {}

    # ── Delta guards track new-trade delta only ───────────────────────────────
    # Initial portfolio delta (stocks + existing options) is kept separately for
    # reporting. Guards start at 0 so that a large stock delta doesn't block all
    # new trades before the loop even begins.
    portfolio_delta:   float            = 0.0
    ticker_delta_used: dict[str, float] = {}

    used_margin = 0.0
    positions: List[Position] = []

    # ── Delta-aware ranking key ───────────────────────────────────────────────
    # Primary  : covered calls first (free margin)
    # Secondary: prefer contracts that REDUCE |portfolio_delta − target_delta|
    # Tertiary : rr_score as tiebreaker within equally delta-beneficial contracts
    def _rank_key(c: OptionContract) -> tuple:
        d_actual     = contract_delta_actual(c.bs["delta"] if c.bs else c.live_delta)
        current_gap  = portfolio_delta - target_delta
        gap_after    = current_gap + d_actual          # adding 1 contract
        delta_benefit= abs(current_gap) - abs(gap_after)  # positive = moves toward target
        is_covered   = c.option_type == "call" and covered_slots.get(c.ticker, 0) > 0
        return (0 if is_covered else 1, -delta_benefit, -c.rr_score)

    ranked = sorted(candidates, key=_rank_key)
    commits_since_sort = 0

    for idx in range(len(ranked)):
        # ── Adaptive re-sort every `resort_every` commits ─────────────────
        if commits_since_sort > 0 and commits_since_sort % resort_every == 0:
            remaining = ranked[idx:]
            remaining.sort(key=_rank_key)
            ranked[idx:] = remaining

        cand = ranked[idx]

        # d_actual: actual portfolio delta contribution per contract (short-adjusted)
        #   short put  → positive  (e.g. chain delta −0.30 → d_actual = +30)
        #   short call → negative  (e.g. chain delta +0.35 → d_actual = −35)
        d_actual = contract_delta_actual(cand.bs["delta"])

        # ── Covered-call slots ────────────────────────────────────────────
        if cand.option_type == "call":
            covered_avail = max(0, covered_slots.get(cand.ticker, 0)
                                   - covered_used.get(cand.ticker, 0))
        else:
            covered_avail = 0

        if cand.option_type == "call" and covered_avail > 0:
            cb = _cost_basis.get(cand.ticker, 0.0)
            if cb > 0 and (cand.strike + cand.bs["price"]) < cb:
                covered_avail = 0

        naked_margin = cand.margin_per_contract

        # ── Max contracts from margin budget ──────────────────────────────
        remaining_margin = margin_budget - used_margin
        free_contracts   = min(covered_avail, max_contracts)
        paid_capacity    = int(remaining_margin // naked_margin) if naked_margin > 0 else max_contracts
        n                = min(free_contracts + paid_capacity, max_contracts)
        if n < min_contracts:
            continue

        # ── Per-ticker margin cap ─────────────────────────────────────────
        t_margin_used      = ticker_margin_used.get(cand.ticker, 0.0)
        t_margin_remaining = ticker_margin_cap - t_margin_used
        if t_margin_remaining <= 0:
            if min(n, covered_avail) < min_contracts:
                continue
            n = min(n, covered_avail)
        elif naked_margin > 0:
            n_covered_cap = min(covered_avail, n)
            n_naked_cap   = min(n - n_covered_cap, int(t_margin_remaining // naked_margin))
            n = n_covered_cap + n_naked_cap
            if n < min_contracts:
                continue

        # ── Portfolio-level delta guard ───────────────────────────────────
        if abs(portfolio_delta + d_actual * n - target_delta) > max_delta_abs:
            best_n = 0
            for test_n in range(n, min_contracts - 1, -1):
                if abs(portfolio_delta + d_actual * test_n - target_delta) <= max_delta_abs:
                    best_n = test_n
                    break
            if best_n < min_contracts:
                continue
            n = best_n

        # ── Per-ticker delta guard ────────────────────────────────────────
        t_delta = ticker_delta_used.get(cand.ticker, 0.0)
        if abs(t_delta + d_actual * n) > max_ticker_delta_abs:
            best_n = 0
            for test_n in range(n, min_contracts - 1, -1):
                if abs(t_delta + d_actual * test_n) <= max_ticker_delta_abs:
                    best_n = test_n
                    break
            if best_n < min_contracts:
                continue
            n = best_n

        # ── Split covered / naked ─────────────────────────────────────────
        n_covered = min(n, covered_avail)
        n_naked   = n - n_covered

        # Cap naked calls per ticker
        if cand.option_type == "call" and n_naked > 0:
            naked_used    = naked_call_used.get(cand.ticker, 0)
            naked_allowed = max(0, max_naked_calls_per_ticker - naked_used)
            if naked_allowed == 0:
                n_naked = 0
                n       = n_covered
                if n < min_contracts:
                    continue
            elif n_naked > naked_allowed:
                n_naked = naked_allowed
                n       = n_covered + n_naked

        # Final margin check for naked portion
        if n_naked > 0 and n_naked * naked_margin > remaining_margin:
            n_naked = int(remaining_margin // naked_margin)
            n       = n_covered + n_naked
            if n < min_contracts:
                continue

        # ── Commit ───────────────────────────────────────────────────────
        margin = n_naked * naked_margin
        used_margin                      += margin
        portfolio_delta                  += d_actual * n
        ticker_delta_used[cand.ticker]    = ticker_delta_used.get(cand.ticker, 0.0) + d_actual * n
        ticker_margin_used[cand.ticker]   = ticker_margin_used.get(cand.ticker, 0.0) + margin
        if cand.ticker in covered_used:
            covered_used[cand.ticker]    += n_covered
        if cand.option_type == "call" and n_naked > 0:
            naked_call_used[cand.ticker]  = naked_call_used.get(cand.ticker, 0) + n_naked

        positions.append(Position(
            contract          = cand,
            contracts         = n,
            total_premium     = cand.bs["price"] * 100 * n,
            total_margin      = margin,
            total_theta       = abs(cand.bs["theta"]) * 100 * n,
            total_delta       = d_actual * n,
            covered_contracts = n_covered,
        ))
        commits_since_sort += 1

    total_vega  = sum(p.contract.bs["vega"]  * 100 * p.contracts for p in positions)
    total_gamma = sum(p.contract.bs["gamma"] * 100 * p.contracts for p in positions)

    return OptimizedPortfolio(
        positions     = positions,
        total_margin  = used_margin,
        total_premium = sum(p.total_premium for p in positions),
        total_theta   = sum(p.total_theta   for p in positions),
        total_delta   = initial_portfolio_delta + portfolio_delta,  # initial (stocks+options) + new trades
        total_vega    = total_vega,
        total_gamma   = total_gamma,
        cash_used_pct = used_margin / free_cash * 100 if free_cash else 0,
        free_cash     = free_cash,
        initial_delta = initial_portfolio_delta,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 8.  REPORTING
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


def print_current_delta(
    total_initial_delta:  float,
    ticker_initial_delta: dict[str, float],
    target_delta:         float = 0.0,
) -> None:
    """Print current portfolio delta breakdown by ticker with distance-to-target."""
    gap = total_initial_delta - target_delta
    print(f"\n  ┌─  CURRENT PORTFOLIO DELTA (before new trades)  {'─'*36}┐")
    print(f"  │  {'TICKER':<10}  {'NET DELTA':>12}  {'DIRECTION':<15}              │")
    print(f"  │  {'─'*10:<10}  {'─'*9:>12}  {'─'*9:<15}              │")
    for ticker, delta in ticker_initial_delta.items():
        direction = "▲ Long" if delta > 0 else ("▼ Short" if delta < 0 else "Neutral")
        print(f"  │  {ticker:<10}  {delta:>+12.1f}  {direction:<15}              │")
    print(f"  │  {'─'*10:<10}  {'─'*9:>12}                                    │")
    direction = "▲ Long" if total_initial_delta > 0 else ("▼ Short" if total_initial_delta < 0 else "Neutral")
    print(f"  │  {'TOTAL':<10}  {total_initial_delta:>+12.1f}  {direction:<15}              │")
    print(f"  │  {'TARGET':<10}  {target_delta:>+12.1f}                                   │")
    print(f"  │  {'GAP':<10}  {gap:>+12.1f}  {'(to neutralise)':15}              │")
    print(f"  └{'─'*81}┘")


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


def print_portfolio(pf: OptimizedPortfolio, target_delta: float = 0.0):
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
        coverage_tag = ""
        if c.option_type == "call" and pos.covered_contracts > 0:
            coverage_tag = (
                " [COVERED]" if pos.covered_contracts == pos.contracts
                else f" [{pos.covered_contracts}COV/{pos.contracts - pos.covered_contracts}NAKED]"
            )
        print(
            f"  {i:>2}  {c.label + coverage_tag:<60} {pos.contracts:>4}  "
            f"${pos.total_premium:>7,.0f}  ${pos.total_margin:>7,.0f}  "
            f"${pos.total_theta:>6.2f}  {pos.total_delta:>+8.1f}"
        )

    new_trade_delta = pf.total_delta - pf.initial_delta
    print(f"\n  {'':>56}{'─────────':>9}  {'────────':>8}  {'────────':>8}")
    print(
        f"  {'NEW TRADES TOTALS':>56}  ${pf.total_premium:>7,.0f}  "
        f"${pf.total_theta:>6.2f}  {new_trade_delta:>+8.1f}"
    )

    ann_theta        = pf.total_theta * 365
    theta_on_margin  = (pf.total_theta * 365 / pf.total_margin * 100) if pf.total_margin else 0
    residual_delta   = pf.total_delta - target_delta

    print(f"\n  ┌─  PORTFOLIO GREEKS & METRICS  {'─'*49}┐")
    print(f"  │  Initial Delta  (before trades) : {pf.initial_delta:>+9.1f}                            │")
    print(f"  │  New Trades Delta               : {new_trade_delta:>+9.1f}                            │")
    print(f"  │  Net Delta      (after trades)  : {pf.total_delta:>+9.1f}                            │")
    print(f"  │  Target Delta                   : {target_delta:>+9.1f}                            │")
    print(f"  │  Residual Gap   (net − target)  : {residual_delta:>+9.1f}                            │")
    print(f"  │  {'─'*77}│")
    print(f"  │  Daily Theta Collected  : ${pf.total_theta:>9.2f}                              │")
    print(f"  │  Annual Theta (est.)    : ${ann_theta:>9,.0f}                              │")
    print(f"  │  Theta / Margin (ann.)  :  {theta_on_margin:>8.1f}%                              │")
    print(f"  │  Net Vega (per 1% IV↑)  : ${pf.total_vega:>9.2f}                              │")
    print(f"  │  Net Gamma              :  {pf.total_gamma:>+9.4f}                              │")
    print(f"  └{'─'*81}┘")


# ═════════════════════════════════════════════════════════════════════════════
# 9.  CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

CONFIG = {
    # ── Cash constraint ───────────────────────────────────────────────────────
    "free_cash":        1_500_000,
    "stock_margin_pct": 0.50,        # Reg-T initial margin for stock holdings

    # ── Tickers ───────────────────────────────────────────────────────────────
    "tickers":          ["SPY", "QQQ", "IWM"],

    # ── Option filters ────────────────────────────────────────────────────────
    "type_filter":      "both",      # "put" | "call" | "both"
    "max_dte":          5,
    "min_premium":      0.10,
    "min_delta":        0.15,        # min |delta| — 25Δ
    "max_delta":        0.30,        # max |delta| — stays OTM

    # ── Allocation constraints ────────────────────────────────────────────────
    "max_contracts":              10,
    "min_contracts":               5,
    "max_delta_abs":             500,   # max |portfolio net delta| band from target
    "max_ticker_delta_abs":      250,   # max |net delta| per ticker
    "target_delta":              0.0,   # 0 = delta-neutral
    "max_margin_pct":            0.60,
    "max_ticker_margin_pct":     0.40,
    "max_naked_calls_per_ticker": 10,
    "resort_every":                3,   # re-rank candidates every N commits for adaptive delta steering

    # ── Risk-reward scoring ───────────────────────────────────────────────────
    "delta_risk_exp":    2.0,
    "gamma_risk_weight": 5.0,
    "dte_sweet_spot":      5,
    "dte_risk_weight":   0.3,

    # ── Market data ───────────────────────────────────────────────────────────
    "chain_strike_count": 50,

    # ── Output ────────────────────────────────────────────────────────────────
    "scanner_top_n":    20,
}


# ═════════════════════════════════════════════════════════════════════════════
# 10. ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def run(cfg: dict = CONFIG):
    print_header()

    # ── 0. Existing portfolio positions ──────────────────────────────────────
    print("\n  Fetching portfolio stock holdings …")
    holdings   = fetch_portfolio_stocks(cfg["tickers"])
    cost_basis = fetch_stock_cost_basis(cfg["tickers"])
    print_portfolio_stocks(holdings, cost_basis)

    print("\n  Fetching current option positions …")
    option_positions = fetch_portfolio_options(cfg["tickers"])

    # ── 1. Live market data ───────────────────────────────────────────────────
    print("\n  Fetching live market data …")
    snapshots, raw_contracts = fetch_market_data(
        cfg["tickers"],
        chain_strike_count=cfg.get("chain_strike_count", 50),
    )
    print_market_data(snapshots)

    # Enrich open option positions with live delta from the chain
    enrich_option_positions_with_delta(option_positions, raw_contracts)
    print_portfolio_options(option_positions)

    # ── 1b. Deduct stock Reg-T margin from free cash ──────────────────────────
    stock_margin_pct   = cfg.get("stock_margin_pct", 0.50)
    stock_market_value = sum(
        holdings.get(t, 0) * snapshots[t].spot
        for t in snapshots if holdings.get(t, 0) > 0
    )
    stock_cost = stock_market_value * stock_margin_pct
    free_cash  = cfg["free_cash"] - stock_cost
    if stock_market_value > 0:
        print(f"\n  ┌─  CASH ADJUSTMENT FOR STOCK HOLDINGS  {'─'*41}┐")
        print(f"  │  Original Free Cash  : ${cfg['free_cash']:>12,.0f}                              │")
        print(f"  │  Stock Market Value  : ${stock_market_value:>12,.0f}                              │")
        print(f"  │  Stock Margin ({stock_margin_pct*100:.0f}%)   : ${stock_cost:>12,.0f}                              │")
        print(f"  │  Adjusted Free Cash  : ${free_cash:>12,.0f}                              │")
        print(f"  └{'─'*81}┘")

    # ── 2. Build option universe ──────────────────────────────────────────────
    print("\n  Building option universe …")
    candidates = build_universe(
        raw_contracts     = raw_contracts,
        type_filter       = cfg["type_filter"],
        max_dte           = cfg["max_dte"],
        min_premium       = cfg["min_premium"],
        min_delta         = cfg["min_delta"],
        max_delta         = cfg["max_delta"],
        delta_risk_exp    = cfg["delta_risk_exp"],
        gamma_risk_weight = cfg["gamma_risk_weight"],
        dte_sweet_spot    = cfg["dte_sweet_spot"],
        dte_risk_weight   = cfg["dte_risk_weight"],
    )
    print(f"  {len(candidates)} candidate contracts generated.")

    # ── 3. Scanner ────────────────────────────────────────────────────────────
    print_scanner(candidates, top_n=cfg["scanner_top_n"])

    # ── 3b. Current portfolio delta (stocks + held options, pre-trade) ────────
    target_delta = cfg.get("target_delta", 5000.0)
    initial_portfolio_delta, initial_ticker_delta = compute_initial_delta(
        holdings         = holdings,
        option_positions = option_positions,
        tickers          = cfg["tickers"],
    )
    print_current_delta(initial_portfolio_delta, initial_ticker_delta, target_delta)

    # ── 4. Optimise ───────────────────────────────────────────────────────────
    print("\n  Running optimiser …")
    portfolio = greedy_optimise(
        candidates                  = candidates,
        free_cash                   = free_cash,
        min_contracts               = cfg.get("min_contracts", 5),
        max_contracts               = cfg.get("max_contracts", 10),
        max_delta_abs               = cfg.get("max_delta_abs", 500),
        max_ticker_delta_abs        = cfg.get("max_ticker_delta_abs", 250),
        target_delta                = target_delta,
        max_margin_pct              = cfg.get("max_margin_pct", 0.6),
        max_ticker_margin_pct       = cfg.get("max_ticker_margin_pct", 0.40),
        holdings                    = holdings,
        max_naked_calls_per_ticker  = cfg.get("max_naked_calls_per_ticker", 10),
        cost_basis                  = cost_basis,
        initial_portfolio_delta     = initial_portfolio_delta,
        initial_ticker_delta        = initial_ticker_delta,
        resort_every                = cfg.get("resort_every", 3),
    )
    print_portfolio(portfolio, target_delta=target_delta)
    print(f"\n{HEADER}\n")
    return portfolio


if __name__ == "__main__":
    cfg = dict(CONFIG)
    if len(sys.argv) > 1:
        overrides = json.loads(sys.argv[1])
        cfg.update(overrides)
        print(f"  Config overrides applied: {overrides}")
    run(cfg)