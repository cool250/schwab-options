import { test } from "node:test";
import assert from "node:assert/strict";
import { taxSummary, isLongTerm, incomeExpenseGroups, estimatedTax } from "./taxSummary.js";

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} != ${b}`);

test("estimated tax at the top rates: 1256 60/40, fees off short-term, margin interest off ordinary", () => {
  const e = estimatedTax({
    s1256: { shortTerm: 4000, longTerm: 6000 },
    other: { shortTerm: 2000, longTerm: 1000 },
    income: 500, deductible: 300, fees: 200,
  });
  // short-term 4000 + 2000 - 200 = 5800; ordinary 5800 + 500 - 300 = 6000; long-term 7000
  assert.deepEqual([e.shortTerm, e.longTerm, e.ordinary, e.taxable, e.capitalLoss], [5800, 7000, 6000, 13000, 0]);
  close(e.federal.ordinary, 2220);
  close(e.federal.longTerm, 1400);
  close(e.federal.niit, 494);
  close(e.state, 1729);
  close(e.total, 2220 + 1400 + 494 + 1729);
  close(e.effective, e.total / 13000);
});

test("estimated tax: a short-term loss offsets long-term gains, a net loss owes nothing", () => {
  const offset = estimatedTax({ s1256: { shortTerm: 0, longTerm: 0 }, other: { shortTerm: -3000, longTerm: 5000 } });
  assert.deepEqual([offset.shortTerm, offset.longTerm, offset.capitalLoss], [0, 2000, 0]);
  close(offset.federal.longTerm, 400);
  const loss = estimatedTax({ s1256: { shortTerm: -400, longTerm: -600 }, other: { shortTerm: 200, longTerm: 0 }, income: 100 });
  assert.deepEqual([loss.shortTerm, loss.longTerm, loss.capitalLoss, loss.ordinary], [0, 0, -800, 100]);
  close(loss.total, 100 * (0.37 + 0.038 + 0.133));
});

test("expenses, fees already in the 1099-B, and income are kept apart", () => {
  const g = incomeExpenseGroups(
    { MARGIN_INTEREST: -120, SHORT_DIVIDEND: -30, INTEREST: 45, DIVIDEND: 10, MONEY_FUND_DIVIDEND: 0 },
    { COMMISSION: -200, OPT_REG_FEE: -12, SEC_FEE: -3 },
  );
  assert.deepEqual(g.deductible, { items: [{ label: "Margin interest", amount: 120 }, { label: "Dividends paid on short shares", amount: 30 }], total: 150 });
  assert.deepEqual(g.inBasis, { items: [{ label: "Commissions", amount: 200 }, { label: "Exchange & regulatory fees", amount: 15 }], total: 215 });
  assert.deepEqual(g.income, { items: [{ label: "Interest on cash", amount: 45 }, { label: "Dividends", amount: 10 }], total: 55 });
});

const opt = (underlying_symbol, total_amount, extra = {}) => ({ underlying_symbol, total_amount, date: "2026-01-05", close_date: "2026-01-20", open_type: "STO", ...extra });
const eq = (symbol, total_amount, extra = {}) => ({ symbol, total_amount, asset_type: "EQUITY", date: "2026-01-05", close_date: "2026-02-10", ...extra });

test("long-term only after the anniversary of the open date", () => {
  assert.equal(isLongTerm({ date: "2025-03-10", close_date: "2026-03-10" }), false);
  assert.equal(isLongTerm({ date: "2025-03-10", close_date: "2026-03-11" }), true);
  assert.equal(isLongTerm({ date: null, close_date: "2026-03-11" }), false);
});

test("futures, futures options and index options are 1256, split 60/40 with the open mark", () => {
  const { s1256 } = taxSummary({
    optionTrades: [opt("ES", 1000), opt("/NQ", -200), opt("$SPX", 300)],
    equityTrades: [eq("/ES", 500, { asset_type: "FUTURE" })],
    open1256: 400,
  });
  assert.deepEqual(
    [s1256.futuresOptions, s1256.indexOptions, s1256.futures, s1256.realized, s1256.total],
    [800, 300, 500, 1600, 2000],
  );
  assert.equal(s1256.longTerm, 1200);
  assert.equal(s1256.shortTerm, 800);
});

test("other trades: written options short-term always, the rest by holding period", () => {
  const year = { date: "2024-06-03", close_date: "2026-02-10" };
  const { other } = taxSummary({
    optionTrades: [opt("AAPL", 100), opt("AAPL", 50, { ...year }), opt("MSFT", 70, { ...year, open_type: "BTO" }), opt("SPY", -30)],
    equityTrades: [eq("AAPL", -400), eq("MSFT", 900, year), eq("SPY", 10, { asset_type: "ETF" })],
  });
  assert.deepEqual(other.equityOptions, { short: 120, long: 70 });
  assert.deepEqual(other.stocks, { short: -390, long: 900 });
  assert.deepEqual([other.shortTerm, other.longTerm], [-270, 970]);
});

test("realized P&L by estimated-tax period, through the last month shown", () => {
  const { periods } = taxSummary({
    lastMonth: 4,
    optionTrades: [opt("ES", 100, { close_date: "2026-03-31" }), opt("AAPL", 40, { close_date: "2026-04-01" })],
    equityTrades: [eq("AAPL", 25, { close_date: "2026-05-29" })],
  });
  assert.deepEqual(periods.map((p) => p.label), ["Jan 1 – Mar 31", "Apr 1 – May 31"]);
  assert.deepEqual([periods[0].s1256, periods[0].total], [100, 100]);
  assert.deepEqual([periods[1].shortTerm, periods[1].total], [65, 65]);
});

test("unknown open mark: the 1256 total is realized only", () => {
  const { s1256 } = taxSummary({ optionTrades: [opt("ES", 100)] });
  assert.equal(s1256.open, null);
  assert.equal(s1256.total, 100);
});
