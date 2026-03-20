"""
Short Put Screener — Schwab API
================================
Screens a watchlist for short put candidates using:
  - IVR (IV Rank) > threshold (default 30)
  - Delta in target range (default 0.15–0.25)
  - DTE in target window (default 21–45)
  - Minimum bid (default $0.20) to filter illiquid garbage

Requires: schwab-py  (`pip install schwab-py`)
Auth:      token.json file created on first run via browser OAuth flow.
"""

from broker import client as schwab_client
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Optional

# ─── Config ───────────────────────────────────────────────────────────────────

API_KEY      = "YOUR_API_KEY"
APP_SECRET   = "YOUR_APP_SECRET"
CALLBACK_URL = "https://127.0.0.1"
TOKEN_PATH   = "token.json"

WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "JPM", "GS",   "XOM",  "SPY",
]

# Screening filters
MIN_IVR        = 30      # only sell when vol is elevated
DELTA_MIN      = 0.15    # absolute value — put deltas are negative
DELTA_MAX      = 0.25
DTE_MIN        = 21
DTE_MAX        = 45
MIN_BID        = 0.20    # skip penny-wide garbage
IV_LOOKBACK    = 252     # trading days for IVR calculation

# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_client() -> schwab_client.Client:
    """Return authenticated Schwab client, creating token if needed."""
    return schwab_client.Client()

# ─── IVR Calculation ──────────────────────────────────────────────────────────

def get_iv_rank(client: schwab_client.Client, symbol: str) -> Optional[float]:
    """
    Compute IV Rank (IVR) for a symbol over the past year.

    IVR = (current_IV - 52w_low) / (52w_high - 52w_low) * 100

    Schwab's option chain response includes 'volatility' on the underlying,
    which is the 30-day implied volatility. We use price history to proxy
    historical IV via HV30 as a fallback when historical option IV isn't stored.

    For production: store daily IV snapshots in a local DB for accurate IVR.
    """
    from_date = (date.today() + timedelta(days=DTE_MIN)).isoformat()
    to_date = (date.today() + timedelta(days=DTE_MAX)).isoformat()

    resp = client.get_chain(
        symbol,
        from_date=from_date,
        to_date=to_date,
        contract_type="PUT",
        strike_count=1,
    )
    if resp is None:
        return None

    current_iv = resp.volatility  # current 30d IV as a percentage (e.g. 28.5)
    if current_iv is None:
        return None
    current_iv = float(current_iv)

    # Pull 1yr daily price history to compute rolling HV as IV proxy
    hist_resp = client.get_price_history(
        symbol,
        period_type="year",
        period=1,
        frequency_type="daily",
    )
    if hist_resp is None:
        return None

    candles = hist_resp.candles
    if len(candles) < IV_LOOKBACK // 2:
        return None  # not enough history

    closes = pd.Series([c.close for c in candles])
    log_returns = closes.div(closes.shift(1)).apply(np.log).dropna()

    # Rolling 30-day historical volatility annualized (proxy for IV history)
    hv30 = log_returns.rolling(30).std() * np.sqrt(252) * 100
    hv30 = hv30.dropna()

    if len(hv30) < 30:
        return None

    iv_52w_low  = hv30.min()
    iv_52w_high = hv30.max()

    if iv_52w_high - iv_52w_low < 1e-6:
        return None  # flat vol history — skip

    ivr = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100
    return round(float(np.clip(ivr, 0, 100)), 1)


# ─── Option Chain Screener ────────────────────────────────────────────────────

def get_put_candidates(
    client: schwab_client.Client,
    symbol: str,
    ivr: float,
) -> list[dict]:
    """
    Pull puts in the DTE window and return those passing delta + bid filters.
    """
    from_date = (date.today() + timedelta(days=DTE_MIN)).isoformat()
    to_date   = (date.today() + timedelta(days=DTE_MAX)).isoformat()

    resp = client.get_chain(
        symbol,
        from_date=from_date,
        to_date=to_date,
        contract_type="PUT",
    )
    if resp is None:
        return []

    underlying_price = resp.underlyingPrice
    candidates = []

    put_exp_map = resp.putExpDateMap or {}
    for exp_key, strikes in put_exp_map.items():
        # exp_key format: "2025-04-17:29"  (date:DTE)
        try:
            exp_str, dte_str = exp_key.split(":")
            dte = int(dte_str)
        except ValueError:
            continue

        if not (DTE_MIN <= dte <= DTE_MAX):
            continue

        for strike_str, contracts in strikes.items():
            strike = float(strike_str)
            for contract in contracts:
                delta = contract.delta
                bid   = contract.bid
                ask   = contract.ask
                iv    = contract.volatility
                theta = contract.theta
                oi    = contract.openInterest or 0

                if delta is None or bid is None:
                    continue

                abs_delta = abs(float(delta))
                bid_price = float(bid)

                if not (DELTA_MIN <= abs_delta <= DELTA_MAX):
                    continue
                if bid_price < MIN_BID:
                    continue

                mid = round((float(bid) + float(ask)) / 2, 2) if ask else bid_price

                candidates.append({
                    "symbol":     symbol,
                    "expiry":     exp_str,
                    "dte":        dte,
                    "strike":     strike,
                    "delta":      round(float(delta), 3),
                    "bid":        bid_price,
                    "mid":        mid,
                    "iv_pct":     round(float(iv), 1) if iv else None,
                    "ivr":        ivr,
                    "theta":      round(float(theta), 3) if theta else None,
                    "open_int":   oi,
                    "underlying": round(underlying_price, 2),
                    "otm_pct":    round((underlying_price - strike) / underlying_price * 100, 1),
                })

    return candidates


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_candidate(row: dict) -> float:
    """
    Simple composite score to rank candidates.
    Higher is better.

    Components:
      - IVR contribution   (higher IVR = better)
      - Theta/day          (more decay = better)
      - OTM buffer         (more cushion = better, but diminishing)
      - DTE sweet spot     (prefer 30–38 DTE — theta:vega ratio)
    """
    ivr_score   = row["ivr"] / 100                         # 0–1
    theta_score = min(abs(row["theta"] or 0) / 0.05, 1)   # cap at $0.05/day
    otm_score   = min(row["otm_pct"] / 10, 1)             # cap at 10% OTM
    dte_score   = 1 - abs(row["dte"] - 34) / 34           # peaks at 34 DTE

    return round(
        0.35 * ivr_score +
        0.30 * theta_score +
        0.20 * otm_score +
        0.15 * dte_score,
        4,
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_screener() -> pd.DataFrame:
    client = get_client()
    all_candidates = []

    for symbol in WATCHLIST:
        print(f"  Scanning {symbol}...", end=" ")

        ivr = get_iv_rank(client, symbol)
        if ivr is None:
            print(f"IVR unavailable, skipping.")
            continue

        print(f"IVR={ivr:.0f}", end=" ")

        if ivr < MIN_IVR:
            print(f"— below threshold ({MIN_IVR}), skip.")
            continue

        candidates = get_put_candidates(client, symbol, ivr)
        print(f"— {len(candidates)} candidates found.")
        all_candidates.extend(candidates)

    if not all_candidates:
        print("\nNo candidates passed all filters today.")
        return pd.DataFrame()

    df = pd.DataFrame(all_candidates)
    df["score"] = df.apply(score_candidate, axis=1)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    display_cols = [
        "score", "symbol", "expiry", "dte", "strike",
        "delta", "bid", "mid", "theta", "ivr", "iv_pct",
        "otm_pct", "open_int", "underlying",
    ]
    return df[display_cols]


if __name__ == "__main__":
    print(f"\nShort Put Screener  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Filters: IVR>{MIN_IVR}, Δ {DELTA_MIN}–{DELTA_MAX}, DTE {DTE_MIN}–{DTE_MAX}, bid>${MIN_BID}")
    print("=" * 70)

    results = run_screener()

    if not results.empty:
        print(f"\nTop candidates:\n")
        print(results.head(10).to_string(index=False))

        out = f"screener_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        results.to_csv(out, index=False)
        print(f"\nFull results saved to {out}")