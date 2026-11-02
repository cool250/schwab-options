// Run with `npm test` (node's built-in runner). The expected figures in
// tests/fixtures/payoff_cases.json are derived by hand and shared with the
// Python side (tests/test_strategy_math.py), so the Analyze page and the
// Strategy Builder can't drift apart.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { findBreakevens, maxLossProfit, netCredit, normCdf, probabilityOfProfit } from "./payoffMath.js";

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

test("POP counts a profit zone when a wing only touches zero", () => {
  // Credit 2 on a 2-wide put spread: zero below 98, so no lower breakeven.
  const legs = [
    { type: "PUT", side: "BUY", strike: 98, premium: 1, qty: 1 },
    { type: "PUT", side: "SELL", strike: 100, premium: 2, qty: 1 },
    { type: "CALL", side: "SELL", strike: 105, premium: 2, qty: 1 },
    { type: "CALL", side: "BUY", strike: 108, premium: 1, qty: 1 },
  ];
  const sigma = 0.25 * Math.sqrt(30 / 365);
  const below = (p) => normCdf((Math.log(p / 102) + (sigma * sigma) / 2) / sigma);
  close(probabilityOfProfit(legs, 102, 0.25, 30, findBreakevens(legs)), below(107) - below(98), 1e-6, "pop");
});
