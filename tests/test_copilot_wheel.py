"""The options-wheel numbers (copilot/wheel.py): notional, leverage and
mode, call coverage (no naked calls), delta ranges, realized P&L and the
loss budget. Notional, coverage, modes and delta ranges come from
tests/fixtures/wheel_cases.json, which frontend/src/utils/wheel.test.js
checks too — Home's New Income ideas use the same rules."""

import json
from pathlib import Path

import pytest

from copilot import wheel

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "wheel_cases.json").read_text())
SETTINGS = {**FIXTURE["settings"], "wheel.loss_budget_pct": 25, "home.take_profit_pct": 75}


@pytest.mark.parametrize("case", FIXTURE["notional"], ids=lambda c: c["name"])
def test_notional(case):
    got = wheel.notional_by_underlying(case["stocks"], case["equity_puts"], case["futures"], case["futures_option_puts"])
    assert got == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["coverage"], ids=lambda c: c["name"])
def test_call_coverage(case):
    got = wheel.call_coverage(case["stocks"], case["equity_calls"], case["futures"], case["futures_option_calls"])
    assert got == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["modes"], ids=lambda c: str(c["leverage"]))
def test_mode_bands(case):
    settings = FIXTURE["settings"]
    assert wheel.risk_mode(case["leverage"], settings["wheel.aggressive_max_leverage_pct"], settings["wheel.defensive_min_leverage_pct"]) == case["mode"]


@pytest.mark.parametrize("case", FIXTURE["delta_bands"], ids=lambda c: str(c["mode"]))
def test_delta_bands(case):
    assert wheel.delta_bands(case["mode"], FIXTURE["settings"]) == case["expected"]


def test_realized_pl_matches_the_reports_page():
    options = [
        {"close_date": "2026-11-03", "type": "CLOSED", "total_amount": 500},
        {"close_date": "2026-11-04", "type": "EXERCISED", "total_amount": 300},
        {"close_date": None, "type": "TRADE", "total_amount": 2800},  # still open: its credit isn't profit
    ]
    equity = [
        {"quantity": 100, "close_price": 510, "total_amount": 1000},
        {"quantity": 100, "close_price": None, "total_amount": -400},  # open lot
        {"quantity": -100, "close_price": 500, "total_amount": 900},   # a short's opening fill
    ]
    assert wheel.realized_pl(options, equity) == 500 + 300 + 1000


def test_snapshot_leverage_mode_delta_ranges_and_loss_budget():
    notional = {"/ES": {"total": 2_000_000}, "/NQ": {"total": 1_000_000}}
    snap = wheel.snapshot(net_liquidity=1_000_000, notional=notional, coverage={}, ytd_realized=80_000, mtd_realized=-5_000, settings=SETTINGS)
    assert snap["leverage_pct"] == 300 and snap["mode"] == "defensive"
    assert snap["new_trade_delta_pct"] == {"put": None, "call": [30, 40]}
    assert snap["loss_budget"] == {"pct_of_ytd": 25, "dollars": 20_000}
    assert snap["realized_pl"] == {"month_to_date": -5_000, "year_to_date": 80_000}
    losing_year = wheel.snapshot(net_liquidity=1_000_000, notional=notional, coverage={}, ytd_realized=-1, mtd_realized=0, settings=SETTINGS)
    assert losing_year["loss_budget"]["dollars"] == 0
    assert wheel.snapshot(net_liquidity=None, notional=notional, coverage={}, ytd_realized=0, mtd_realized=0, settings=SETTINGS)["mode"] is None
