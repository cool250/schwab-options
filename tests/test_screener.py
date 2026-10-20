"""The Options Screener (MarketService.screen_options and
service/market/screener_strategies.py): row math, filters, and per-ticker
error isolation — through a stand-in chain provider."""

import pytest

from service.market import MarketService
from tests.market_helpers import SPOT, FakeChainProvider, contract

CONTRACTS = [contract(k, t) for k in range(90, 121) for t in ("PUT", "CALL")]


def screen(strategy, symbols=("X",), screener=None, **kw):
    provider = FakeChainProvider(screener=screener or {"X": CONTRACTS})
    args = dict(min_dte=0, max_dte=60, min_otm_pct=-50, max_otm_pct=50, strategy=strategy,
                min_abs_delta=None, max_abs_delta=None, limit=10_000)
    args.update(kw)
    return MarketService(chain_provider=provider).screen_options(list(symbols), **args)


def row_for(result, strike, type_):
    return next(r for r in result["results"] if r["strike"] == strike and r["type"] == type_)


def test_short_put_otm_roi_is_premium_over_strike():
    row = row_for(screen("PUT"), 100, "PUT")
    assert row["premium"] == row["bid"]
    assert row["capital"] == 100
    assert row["roi"] == pytest.approx(row["bid"] / 100 * 100)
    assert row["annualizedRoi"] == pytest.approx(row["roi"] * 365 / 30)
    assert row["breakeven"] == pytest.approx(100 - row["bid"])
    assert row["otmPct"] == pytest.approx((SPOT - 100) / SPOT * 100)


def test_itm_put_roi_excludes_intrinsic():
    row = row_for(screen("PUT"), 110, "PUT")
    assert row["roi"] == pytest.approx((row["bid"] - (110 - SPOT)) / 110 * 100)


def test_short_call_capital_is_spot():
    row = row_for(screen("CALL"), 110, "CALL")
    assert row["capital"] == SPOT
    assert row["breakeven"] == pytest.approx(SPOT - row["bid"])


def test_results_rank_by_annualized_roi():
    rois = [r["annualizedRoi"] for r in screen("PUT")["results"]]
    assert rois == sorted(rois, reverse=True)


def test_long_call_ranks_by_leverage_at_the_ask():
    result = screen("LONG_CALL")
    row = row_for(result, 110, "CALL")
    assert row["premium"] == row["ask"]
    assert row["leverage"] == pytest.approx(abs(row["delta"]) * SPOT / row["ask"])
    assert row["breakeven"] == pytest.approx(110 + row["ask"])
    levs = [r["leverage"] for r in result["results"]]
    assert levs == sorted(levs, reverse=True)


def test_delta_filter_uses_absolute_delta_and_drops_unknown_delta():
    contracts = [dict(c) for c in CONTRACTS]
    contracts[0]["delta"] = None
    result = screen("PUT", screener={"X": contracts}, min_abs_delta=0.2, max_abs_delta=0.4)
    assert result["results"]
    assert all(0.2 <= abs(r["delta"]) <= 0.4 for r in result["results"])


def test_one_bad_ticker_does_not_sink_the_screen():
    result = screen("PUT", symbols=("X", "BAD", "EMPTY"), screener={"X": CONTRACTS, "BAD": RuntimeError("boom"), "EMPTY": None})
    assert result["results"]
    errors = {e["symbol"]: e["message"] for e in result["errors"]}
    assert set(errors) == {"BAD", "EMPTY"}
    assert "boom" not in errors["BAD"]  # internal error text stays in the logs


def test_ratio_put_rows():
    result = screen("RATIO_PUT")
    assert result["results"]
    for row in result["results"]:
        long, short = sorted(row["legs"], key=lambda l: -l["strike"])
        assert long["qty"] == 1 and short["qty"] == -2
        assert row["credit"] == pytest.approx(2 * short["bid"] - long["ask"]) and row["credit"] > 0
        # Capital = loss if the stock goes to zero.
        assert row["capital"] == pytest.approx(2 * short["strike"] - long["strike"] - row["credit"])


def test_jade_lizard_rows_have_no_upside_risk():
    result = screen("JADE_LIZARD")
    assert result["results"]
    for row in result["results"]:
        legs = {(l["type"], l["qty"]): l for l in row["legs"]}
        put, short_call, long_call = legs[("PUT", -1)], legs[("CALL", -1)], legs[("CALL", 1)]
        assert put["strike"] < short_call["strike"] < long_call["strike"]
        assert row["credit"] >= long_call["strike"] - short_call["strike"]
        assert row["maxProfit"] == pytest.approx(row["credit"])
