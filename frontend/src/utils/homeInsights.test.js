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

test("implied volatility round-trips through Black-Scholes", async () => {
  const { impliedVol } = await import("./homeInsights.js");
  const { blackScholes } = await import("./payoffMath.js");
  const price = blackScholes(7000, 6800, 10, 0.22, false);
  assert.ok(Math.abs(impliedVol(price, 7000, 6800, 10, "PUT") - 0.22) < 1e-4);
  assert.equal(impliedVol(150, 7000, 7150, 10, "PUT"), null, "below intrinsic");
});

test("naked short option requirement", async () => {
  const { shortOptionRequirement } = await import("./homeInsights.js");
  // Put 90 on a 100 stock, premium 1: max(20 - 10, 9) + 1.
  assert.equal(shortOptionRequirement("PUT", 90, 100, 1), 11);
  // In the money the requirement rises: max(16 - 0, 9) + 12.
  assert.equal(shortOptionRequirement("PUT", 90, 80, 12), 28);
});

const OPTS = { futuresPct: 10, ivRise: 20 };

test("stocks: P&L moves with price and a drop frees no margin", async () => {
  const { stressBook, cushionChange, marginCallMove } = await import("./homeInsights.js");
  const book = stressBook([{ kind: "stock", qty: 1000, price: 1000, req: 250000 }]);
  assert.deepEqual(cushionChange(book, -0.10, OPTS), { pnl: -100000, reqRise: 0, change: -100000 });
  // Short shares: a rally loses and raises the requirement.
  const short = stressBook([{ kind: "stock", qty: -1000, price: 1000, req: 300000 }]);
  const up = cushionChange(short, 0.10, OPTS);
  assert.ok(Math.abs(up.change - (-100000 - 30000)) < 1e-6);
  assert.ok(Math.abs(marginCallMove(100000, book, -1, OPTS) + 0.10) < 1e-6);
  assert.equal(marginCallMove(100000, book, 1, OPTS), null, "a rally never hurts a long book");
});

test("a short put loses more than delta says, and more again with the volatility rise", async () => {
  const { stressBook, cushionChange } = await import("./homeInsights.js");
  const { blackScholes } = await import("./payoffMath.js");
  const put = { kind: "option", root: null, type: "PUT", strike: 95, dte: 30, qty: -10, mult: 100, spot: 100, mid: null, delta: -0.25, req: 20000 };
  put.mid = blackScholes(100, 95, 30, 0.25, false);
  const book = stressBook([put]);
  const flatVol = cushionChange(book, -0.10, { ...OPTS, ivRise: 0 });
  const shocked = cushionChange(book, -0.10, OPTS);
  const linear = -0.25 * -10 * 100 * 100 * -0.10; // delta x qty x mult x spot x move
  assert.ok(flatVol.pnl < linear, `repriced ${flatVol.pnl} vs delta ${linear}`);
  assert.ok(shocked.pnl < flatVol.pnl);
  assert.ok(shocked.reqRise > 0, "the put's requirement rises as it nears the money");
});

test("futures are margined per root on a scan, never freeing margin", async () => {
  const { stressBook, cushionChange } = await import("./homeInsights.js");
  const book = stressBook([{ kind: "future", root: "ES", qty: 1, price: 7000, mult: 50 }]);
  const down = cushionChange(book, -0.10, OPTS);
  assert.ok(Math.abs(down.pnl + 35000) < 1e-6);
  assert.ok(Math.abs(down.reqRise) < 1e-6);
  const up = cushionChange(book, 0.10, OPTS);
  assert.ok(Math.abs(up.reqRise - 3500) < 1e-6, "10% of the larger notional");
});

test("positions with no price are left out and counted", async () => {
  const { stressBook } = await import("./homeInsights.js");
  const book = stressBook([
    { kind: "stock", qty: 1, price: null },
    { kind: "option", type: "PUT", strike: 90, dte: 5, qty: -1, mult: 100, spot: 100, iv: null, mid: null, delta: null },
    { kind: "option", type: "PUT", strike: 90, dte: 5, qty: -1, mult: 100, spot: 100, iv: 0.3 },
  ]);
  assert.equal(book.unpriced, 2);
  assert.equal(book.positions.length, 1);
});
