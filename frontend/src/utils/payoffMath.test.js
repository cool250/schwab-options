// Run with `npm test` (node's built-in runner). The expected figures in
// tests/fixtures/payoff_cases.json are derived by hand and shared with the
// Python side (tests/test_strategy_math.py), so the Analyze page and the
// Strategy Builder can't drift apart.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { findBreakevens, maxLossProfit, netCredit, probabilityOfProfit } from "./payoffMath.js";

const fixture = JSON.parse(readFileSync(new URL("../../../tests/fixtures/payoff_cases.json", import.meta.url)));
const close = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);

for (const c of fixture.cases) {
  // Per share (multiplier 1), one unit — the fixture's convention.
  const legs = c.legs.map((l) => ({
    type: l.type, strike: l.strike, premium: l.price,
    side: l.qty < 0 ? "SELL" : "BUY", qty: Math.abs(l.qty), multiplier: 1,
  }));

  test(c.name, () => {
    close(netCredit(legs), c.netPremium, 1e-9, "net premium");
    const { maxProfit, maxLoss } = maxLossProfit(legs);
    if (c.maxProfit === null) assert.equal(maxProfit, Infinity);
    else close(maxProfit, c.maxProfit, 1e-9, "max profit");
    if (c.maxLoss === null) assert.equal(maxLoss, -Infinity);
    else close(maxLoss, c.maxLoss, 1e-9, "max loss");
    const breakevens = findBreakevens(legs);
    assert.equal(breakevens.length, c.breakevens.length);
    breakevens.forEach((b, i) => close(b, c.breakevens[i], 0.005, "breakeven"));
    close(probabilityOfProfit(legs, fixture.spot, fixture.iv, fixture.dte, breakevens), c.pop, 1e-6, "pop");
  });
}
