"""Expiration payoff math (service/shared/strategy_math.py), checked against
hand-derived cases shared with the Analyze page's JavaScript
(frontend/src/utils/payoffMath.test.js)."""

import json
import math
from pathlib import Path

import pytest

from service.shared.strategy_math import net_premium, payoff, payoff_profile, probability_of_profit

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "payoff_cases.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_payoff_case(case):
    legs = case["legs"]
    credit = net_premium(legs)
    assert credit == pytest.approx(case["netPremium"])
    profile = payoff_profile(legs, credit)
    assert profile["maxProfit"] == (None if case["maxProfit"] is None else pytest.approx(case["maxProfit"]))
    assert profile["maxLoss"] == (None if case["maxLoss"] is None else pytest.approx(case["maxLoss"]))
    assert profile["breakevens"] == pytest.approx(case["breakevens"])
    for b in profile["breakevens"]:
        assert payoff(legs, credit, b) == pytest.approx(0, abs=1e-9)
    pop = probability_of_profit(legs, credit, FIXTURE["spot"], FIXTURE["iv"], FIXTURE["dte"])
    assert pop == pytest.approx(case["pop"], abs=1e-9)


def test_pop_counts_a_profit_zone_when_a_wing_only_touches_zero():
    # Credit 2 on a 2-wide put spread: zero below 98, so no lower breakeven.
    legs = [{"type": "PUT", "strike": 98, "qty": 1}, {"type": "PUT", "strike": 100, "qty": -1},
            {"type": "CALL", "strike": 105, "qty": -1}, {"type": "CALL", "strike": 108, "qty": 1}]
    sigma = 0.25 * math.sqrt(30 / 365)
    below = lambda p: 0.5 * (1 + math.erf((math.log(p / 102) + sigma * sigma / 2) / sigma / math.sqrt(2)))
    assert probability_of_profit(legs, 2.0, 102, 0.25, 30) == pytest.approx(below(107) - below(98))


def test_pop_needs_iv_and_spot():
    legs = FIXTURE["cases"][0]["legs"]
    assert probability_of_profit(legs, 2.0, 105, None, 30) is None
    assert probability_of_profit(legs, 2.0, 0, 0.25, 30) is None
