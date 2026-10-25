// Run with `npm test`. The Home page's rules (utils/homeInsights.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  futuresMarginEstimate, contractsAffordable, futuresIdeaNumbers, takeProfitCandidates,
  equityShort, moneyness, expiringSoon, uncoveredShares, concentration, expiryCalendar,
} from "./homeInsights.js";

test("futures margin is pct of notional, and an unpriced contract is counted", () => {
  const { total, unpriced } = futuresMarginEstimate(
    [{ symbol: "ES", quantity: 6 }, { symbol: "NQ", quantity: -4 }, { symbol: "RTY", quantity: 1 }],
    { ES: 7700, NQ: 29000 }, 15);
  assert.equal(total, 6 * 7700 * 50 * 0.15 + 4 * 29000 * 20 * 0.15);
  assert.equal(unpriced, 1);
});

test("contracts affordable at the margin estimate", () => {
  // One /ES at 7,000 x $50 x 15% = $52,500 margin.
  assert.equal(contractsAffordable(200000, 7000, "/ES", 15), 3);
  assert.equal(contractsAffordable(0, 7000, "/ES", 15), 0);
});

test("a futures put idea's credit, margin and return on margin", () => {
  const n = futuresIdeaNumbers({ underlying: "/ES", type: "PUT", strike: 7000, spot: 7200, premium: 10, dte: 5 }, 15);
  assert.equal(n.credit, 500);
  assert.equal(n.margin, 7000 * 50 * 0.15);
  assert.ok(Math.abs(n.returnOnMargin - (500 / 52500) * 100) < 1e-9);
  assert.ok(Math.abs(n.annualized - n.returnOnMargin * 365 / 5) < 1e-9);
});

test("take profit lists shorts that kept at least the threshold", () => {
  const rows = [{ key: "a", credit: 1000, pl: 800 }, { key: "b", credit: 1000, pl: 500 }, { key: "c", credit: 1000, pl: null }];
  assert.deepEqual(takeProfitCandidates(rows, 75).map((r) => [r.key, r.kept]), [["a", 80]]);
});

test("an equity short's credit and moneyness", () => {
  const s = equityShort({ symbol: "Q", ticker: "QQQ", strike_price: 700, expiration_date: "2026-10-30", days_to_expiry: 3,
    quantity: -2, trade_price: 1.5, total_value: 200, underlying_price: 720 }, "PUT");
  assert.equal(s.credit, 300);
  assert.equal(equityShort({ quantity: 1 }, "PUT"), null, "longs aren't shorts");
  assert.equal(moneyness(s, 2).status, "otm");
  assert.equal(moneyness({ ...s, underlyingPrice: 705 }, 2).status, "at_risk");
  assert.equal(moneyness({ ...s, underlyingPrice: 690 }, 2).status, "itm");
  assert.equal(moneyness({ type: "CALL", strike: 700, underlyingPrice: 680 }, 2).status, "otm");
});

test("expiring soon puts the riskiest first", () => {
  const list = expiringSoon([
    { key: "far", dte: 20, type: "PUT", strike: 100, underlyingPrice: 120 },
    { key: "safe", dte: 2, type: "PUT", strike: 100, underlyingPrice: 120 },
    { key: "itm", dte: 4, type: "PUT", strike: 100, underlyingPrice: 95 },
  ], 7, 2);
  assert.deepEqual(list.map((s) => s.key), ["itm", "safe"]);
});

test("uncovered shares: long shares beyond short calls, short shares beyond short puts", () => {
  const stocks = [{ symbol: "GOOG", quantity: 200, current_price: 300 }, { symbol: "QQQ", quantity: -1100, current_price: 700 }];
  const calls = [{ ticker: "GOOG", quantity: -1 }];
  const puts = [{ ticker: "QQQ", quantity: -11 }];
  assert.deepEqual(uncoveredShares(stocks, puts, calls).map((u) => [u.ticker, u.side, u.contracts]), [["GOOG", "CALL", 1]]);
});

test("concentration flags tickers above the share of net liq", () => {
  const rows = concentration([{ symbol: "SPY", quantity: -1300, current_price: 760 }], [{ ticker: "IWM", quantity: -5, strike_price: 280 }], 2000000, 25);
  assert.deepEqual(rows.map((r) => r.ticker), ["SPY"]);
});

test("expiry calendar groups shorts by date within the window", () => {
  const cal = expiryCalendar([
    { expiration: "2026-10-27", credit: 100 }, { expiration: "2026-10-27", credit: 50 },
    { expiration: "2026-10-30", credit: 10 }, { expiration: "2026-12-18", credit: 999 },
  ], 10, "2026-10-25");
  assert.deepEqual(cal, [{ date: "2026-10-27", count: 2, credit: 150 }, { date: "2026-10-30", count: 1, credit: 10 }]);
});

test("margin cushion under a market move, and the move to a margin call", async () => {
  const { marginSensitivity, cushionAfter, moveToMarginCall } = await import("./homeInsights.js");
  // Long $100k of stock (25% req), short $200k (30% req): net short.
  const s = marginSensitivity([{ pnl: 100000, req: 25000 }, { pnl: -200000, req: 60000 }]);
  assert.equal(s.net, -100000 - 85000);
  assert.equal(cushionAfter(500000, s, 0.05), 500000 - 0.05 * 185000);
  // A rally hurts a net-short book: margin call at about +270%.
  assert.ok(Math.abs(moveToMarginCall(500000, s) - 500000 / 185000) < 1e-9);
  assert.equal(moveToMarginCall(500000, { net: 0 }), null);
});
