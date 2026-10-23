"""The Analyze page's Strategy Builder (service/market/strategy_builder.py),
solved against a synthetic chain (tests/market_helpers.py)."""

import pytest

from service.market import strategy_builder as sb
from tests.market_helpers import SPOT, make_chain

CHAIN = make_chain()


def legs_by_key(candidate):
    return {leg["key"]: leg for leg in candidate["legs"]}


def puts():
    return [row["put"] for row in CHAIN["chain"]]


def test_short_put_by_delta_picks_the_closest_delta():
    best = sb.build("SHORT_PUT", {"short_put": {"mode": "delta", "value": 0.30}}, CHAIN)["best"]
    leg = legs_by_key(best)["short_put"]
    closest = min(puts(), key=lambda c: abs(abs(c["delta"]) - 0.30))
    assert leg["strike"] == closest["strike"]
    assert best["netPremium"] == pytest.approx(leg["mid"])
    assert best["maxLoss"] == pytest.approx(-(leg["strike"] - leg["mid"]))


def test_put_credit_spread_width_and_risk():
    best = sb.build("PUT_CREDIT_SPREAD", {
        "short_put": {"mode": "strike", "value": 100}, "long_put": {"mode": "width", "value": 5},
    }, CHAIN)["best"]
    legs = legs_by_key(best)
    assert (legs["short_put"]["strike"], legs["long_put"]["strike"]) == (100, 95)
    credit = legs["short_put"]["mid"] - legs["long_put"]["mid"]
    assert best["netPremium"] == pytest.approx(credit)
    assert best["maxProfit"] == pytest.approx(credit)
    assert best["maxLoss"] == pytest.approx(-(5 - credit))
    assert best["returnOnRisk"] == pytest.approx(credit / (5 - credit))
    assert best["breakevens"] == pytest.approx([100 - credit])
    # Natural price: sell at the bid, buy at the ask.
    assert best["naturalPremium"] == pytest.approx(legs["short_put"]["bid"] - legs["long_put"]["ask"])


def test_straddle_uses_one_strike_nearest_spot():
    legs = legs_by_key(sb.build("SHORT_STRADDLE", {}, CHAIN)["best"])
    assert legs["short_put"]["strike"] == legs["short_call"]["strike"] == round(SPOT)


def test_iron_condor_keeps_order_and_wings():
    legs = legs_by_key(sb.build("IRON_CONDOR", {}, CHAIN)["best"])
    assert legs["long_put"]["strike"] < legs["short_put"]["strike"] < legs["short_call"]["strike"] < legs["long_call"]["strike"]
    assert legs["short_put"]["strike"] - legs["long_put"]["strike"] == 5
    assert legs["long_call"]["strike"] - legs["short_call"]["strike"] == 5


def test_jade_lizard_credit_covers_the_call_spread():
    result = sb.build("JADE_LIZARD", {}, CHAIN)
    for cand in [result["best"], *result["alternatives"]]:
        legs = legs_by_key(cand)
        assert cand["netPremium"] >= legs["long_call"]["strike"] - legs["short_call"]["strike"]
        assert cand["maxLoss"] is not None and cand["maxProfit"] is not None


def test_ratio_put_opens_for_a_credit_with_two_short_puts():
    best = sb.build("RATIO_PUT", {}, CHAIN)["best"]
    legs = legs_by_key(best)
    assert legs["short_put"]["qty"] == -2 and legs["long_put"]["qty"] == 1
    assert legs["short_put"]["strike"] < legs["long_put"]["strike"]
    assert best["netPremium"] > 0


def test_covered_call_counts_the_shares_in_risk_and_return():
    best = sb.build("COVERED_CALL", {"short_call": {"mode": "strike", "value": 105}}, CHAIN)["best"]
    call = legs_by_key(best)["short_call"]
    credit = call["mid"]
    assert call["strike"] == 105 and call["qty"] == -1
    assert best["shares"] == {"qty": 1, "price": SPOT}
    assert best["netPremium"] == pytest.approx(credit)  # the shares carry no premium
    # Capped upside (the shares cover the call), not the naked call's unlimited loss.
    assert best["maxProfit"] == pytest.approx(credit + 105 - SPOT)
    assert best["maxLoss"] == pytest.approx(credit - SPOT)
    assert best["breakevens"] == pytest.approx([SPOT - credit])
    assert best["returnOnRisk"] == pytest.approx((credit + 105 - SPOT) / (SPOT - credit))
    assert best["annualizedReturn"] is not None
    assert best["netDelta"] == pytest.approx(1 + -1 * call["delta"])


def test_ratio_call_opens_for_a_credit_with_two_higher_short_calls():
    best = sb.build("RATIO_CALL", {}, CHAIN)["best"]
    legs = legs_by_key(best)
    assert legs["short_call"]["qty"] == -2 and legs["long_call"]["qty"] == 1
    assert legs["long_call"]["strike"] < legs["short_call"]["strike"]
    assert best["netPremium"] > 0
    assert best["maxLoss"] is None  # the extra short call is uncovered


def test_debit_strategy_opens_for_a_debit():
    best = sb.build("CALL_DEBIT_SPREAD", {}, CHAIN)["best"]
    assert best["netPremium"] < 0
    assert best["annualizedReturn"] is None  # only credit trades annualize


def test_unreachable_target_explains_why():
    result = sb.build("SHORT_PUT", {"short_put": {"mode": "delta", "value": 0.05}}, CHAIN, target=50)
    assert result["best"] is None
    assert "target" in result["reasons"][0]


def test_sigma_placement_needs_iv():
    chain = {**CHAIN, "iv": None}
    result = sb.build("SHORT_PUT", {"short_put": {"mode": "sigma", "value": 1}}, chain)
    assert result["best"] is None and "implied volatility" in result["reasons"][0]


def test_zero_bid_contracts_are_never_sold():
    chain = make_chain()
    for row in chain["chain"]:
        row["put"]["bid"] = 0.0
    result = sb.build("SHORT_PUT", {}, chain)
    assert result["best"] is None


@pytest.mark.parametrize("strategy, params, message", [
    ("NOPE", {}, "Unknown strategy"),
    ("SHORT_PUT", {"short_put": {"mode": "delta", "value": 1.5}}, "delta must be between"),
    ("SHORT_PUT", {"short_put": {"mode": "teleport", "value": 1}}, "placement must be one of"),
    ("PUT_CREDIT_SPREAD", {"long_put": {"mode": "steps", "value": 1.5}}, "whole number"),
])
def test_bad_parameters_are_rejected(strategy, params, message):
    with pytest.raises(sb.StrategyParamError, match=message):
        sb.resolve_params(strategy, params)


def test_combine_prefers_the_requested_placement_then_annualized_return():
    near = sb.build("SHORT_PUT", {}, make_chain(dte=10, expiration="2026-10-30"))
    far = sb.build("SHORT_PUT", {}, make_chain(dte=45, expiration="2026-12-04"))
    combined = sb.combine("SHORT_PUT", [far, near])
    best = combined["best"]
    # Both sit exactly on the requested delta (distance 0); the shorter
    # expiration annualizes higher.
    assert best["expirationDate"] == "2026-10-30"
    assert combined["alternatives"][0]["expirationDate"] == "2026-12-04"


def test_every_template_builds_on_a_normal_chain():
    for template_id in sb.TEMPLATES:
        result = sb.build(template_id, {}, CHAIN)
        assert result["best"] is not None, (template_id, result["reasons"])
