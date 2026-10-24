// Run with `npm test`. Unrealized P&L of open futures and futures-option
// rows (utils/positionPl.js), as the Positions page and Reports show it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { futuresOptionContracts, futuresOptionRowPl, futuresRowPl, stockRowPl } from "./positionPl.js";

test("a short futures option gains what it lost in value", () => {
  // Sold 2 NQ puts at 136 ($20/pt): entry value +5,440; now bid 100.
  const row = { symbol: "Q", quantity: -2, multiplier: 20, total_value: 5440 };
  assert.equal(futuresOptionRowPl(row, { Q: 100 }), 5440 - 100 * 2 * 20);
});

test("a ratio spread is priced leg by leg", () => {
  // Long 1 at 30, short 2 at 20 ($50/pt): entry value (2*20 - 30) * 50 = 500.
  const row = { multiplier: 50, total_value: 500, long_leg: { symbol: "L", amount: 1 }, short_leg: { symbol: "S", amount: 2 } };
  assert.equal(futuresOptionRowPl(row, { L: 10, S: 4 }), 500 - (2 * 4 - 10) * 50);
  assert.equal(futuresOptionRowPl(row, { L: 10 }), null, "unpriced until both legs are quoted");
});

test("an outright future is (price - entry) x quantity x point value", () => {
  assert.equal(futuresRowPl({ symbol: "ES", quantity: 2, trade_price: 7700 }, { ES: 7650 }), -50 * 2 * 50);
  assert.equal(futuresRowPl({ symbol: "NQ", quantity: -1, trade_price: 29000 }, { NQ: 28900 }), 100 * 20);
  assert.equal(futuresRowPl({ symbol: "ES", quantity: 1, trade_price: 7700 }, {}), null);
});

test("quote requests cover both legs of a spread", () => {
  const contracts = futuresOptionContracts(
    [{ ticker: "ES", expiration_date: "2026-10-30", long_leg: { symbol: "L", strike_price: 7700 }, short_leg: { symbol: "S", strike_price: 7600 } }],
    [{ ticker: "NQ", expiration_date: "2026-10-30", symbol: "C", strike_price: 29500 }],
  );
  assert.deepEqual(contracts.map((c) => [c.key, c.underlying, c.type]), [["L", "/ES", "PUT"], ["S", "/ES", "PUT"], ["C", "/NQ", "CALL"]]);
});

test("stock from an assignment is valued at its fill price, not Schwab's premium-adjusted price", () => {
  // Short 1,100 assigned at 610.91 on average; Schwab shows 654.46 with the premium folded in.
  const stock = { quantity: -1100, current_price: 700, broker_pl: (654.46 - 700) * 1100 };
  assert.ok(Math.abs(stockRowPl(stock, 610.91) - (610.91 - 700) * 1100) < 1e-6);
});

test("stock whose fills history doesn't cover keeps Schwab's figure", () => {
  assert.equal(stockRowPl({ quantity: 200, current_price: 317, broker_pl: 27690 }, null), 27690);
});
