// Run with `npm test`. The options-wheel rules Home's New Income ideas use
// (utils/wheel.js). The notional, coverage, mode and delta-range cases come
// from tests/fixtures/wheel_cases.json, shared with the copilot's
// copilot/wheel.py (tests/test_copilot_wheel.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  assignedResult, callCoverage, deltaBands, freeLots, leverageAfter, notionalByUnderlying, putsUnderLeverage, riskMode, wheelSnapshot,
} from "./wheel.js";

const fixture = JSON.parse(readFileSync(new URL("../../../tests/fixtures/wheel_cases.json", import.meta.url)));
const rules = fixture.settings;

for (const c of fixture.notional) {
  test(`notional: ${c.name}`, () => {
    assert.deepEqual(notionalByUnderlying({ stocks: c.stocks, equityPuts: c.equity_puts, futures: c.futures, futuresOptionPuts: c.futures_option_puts }), c.expected);
  });
}

for (const c of fixture.coverage) {
  test(`coverage: ${c.name}`, () => {
    assert.deepEqual(callCoverage({ stocks: c.stocks, equityCalls: c.equity_calls, futures: c.futures, futuresOptionCalls: c.futures_option_calls }), c.expected);
  });
}

test("modes and delta ranges", () => {
  for (const c of fixture.modes) {
    assert.equal(riskMode(c.leverage, rules["wheel.aggressive_max_leverage_pct"], rules["wheel.defensive_min_leverage_pct"]), c.mode);
  }
  for (const c of fixture.delta_bands) assert.deepEqual(deltaBands(c.mode, rules), c.expected);
});

const book = (netLiquidity) => wheelSnapshot({
  netLiquidity, rules,
  futures: [{ symbol: "ES", quantity: 2, current_price: 7500 }],  // 750,000 notional
});

test("the snapshot sets the mode from leverage", () => {
  assert.equal(book(1_000_000).leveragePct, 75);
  assert.equal(book(1_000_000).mode, "aggressive");
  assert.equal(book(400_000).mode, "neutral");
  assert.deepEqual(book(200_000).deltaBands, { put: null, call: [30, 40] });
  assert.equal(book(null).mode, null);
});

test("new puts are sized to stay below the defensive band", () => {
  const snap = book(1_000_000);  // room to 300%: 3,000,000 - 750,000 = 2,250,000
  // /ES 7000 put: 350,000 each -> 6 stays below (2,100,000), a 7th would pass it.
  assert.equal(putsUnderLeverage(snap, 7000, 50), 6);
  assert.ok(leverageAfter(snap, 6 * 350_000) < 300);
  // Exactly reaching the band isn't below it.
  assert.equal(putsUnderLeverage(snap, 9000, 50), 4);  // 450,000 each: 5 would be exactly 300%
  assert.equal(putsUnderLeverage(book(200_000), 7000, 50), 0);
});

test("a new call covers the oldest lot left after existing short calls", () => {
  const es = { symbol: "ES", lots: [
    { date: "2026-11-03", quantity: 2, trade_price: 7650 },
    { date: "2026-10-30", quantity: 2, trade_price: 7700 },
    { date: "2026-11-02", quantity: 1, trade_price: 7700 },
  ] };
  // 5 short calls, 1 covered by a long call: the 4 oldest futures are used.
  const lots = freeLots(es, { short_calls: 5, covered_by: { long_calls: 1 } });
  assert.deepEqual(lots, [{ date: "2026-11-03", entry: 7650 }]);
  assert.equal(assignedResult(7650, 2137.5, lots[0], 50), 2137.5);           // exits at entry: keeps the credit
  assert.equal(assignedResult(7600, 500, lots[0], 50), -50 * 50 + 500);      // below entry: locks in a loss
  assert.equal(assignedResult(7600, 500, undefined, 50), null);
});
