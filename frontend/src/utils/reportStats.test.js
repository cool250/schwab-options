import { test } from "node:test";
import assert from "node:assert/strict";
import { placedTradeStats } from "./reportStats.js";

const trade = (date, order_id, asset_class = "OPTION", position_effect = "OPENING") => ({ date, order_id, asset_class, position_effect });

test("placed trades are counted per month: legs, orders, sides, assets and days", () => {
  const { months, total } = placedTradeStats({
    lastMonth: 1,
    marketDays: ["2026-01-02", "2026-01-05", "2026-02-02", "2026-02-03"],
    trades: [
      trade("2026-01-02", "1"), trade("2026-01-02", "1"),          // a two-leg order
      trade("2026-01-05", "2", "OPTION", "CLOSING"),
      trade("2026-02-03", "3", "FUTURE", null),
      trade("2026-02-03", "4", "ETF", "CLOSING"),
      trade("2026-03-02", "5"),                                    // after lastMonth
    ],
  });
  const [jan, feb] = months;
  assert.deepEqual([jan.trades, jan.orders, jan.opening, jan.closing, jan.daysTraded, jan.marketDays], [3, 2, 2, 1, 2, 2]);
  assert.deepEqual([feb.trades, feb.orders, feb.futures, feb.stocks, feb.daysTraded, feb.marketDays], [2, 2, 1, 1, 1, 2]);
  assert.deepEqual([total.trades, total.orders, total.daysTraded, total.marketDays], [5, 4, 3, 4]);
});

test("holding period of the closed trades, in calendar days", () => {
  const { holding } = placedTradeStats({
    closedTrades: [
      { date: "2026-01-05", close_date: "2026-01-09" },
      { date: "2026-01-05", close_date: "2026-01-05" },
      { date: "2026-01-05", close_date: "2026-02-04" },
      { date: null, close_date: "2026-01-09" },   // open unknown: left out
    ],
  });
  assert.deepEqual(holding, { avg: (4 + 0 + 30) / 3, median: 4, n: 3 });
});

test("no closed trades: no holding period", () => {
  assert.equal(placedTradeStats({}).holding, null);
});
