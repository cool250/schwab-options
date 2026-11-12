import { test } from "node:test";
import assert from "node:assert/strict";
import { nyseHolidays, marketDays } from "./marketCalendar.js";

test("2026 NYSE holidays, with Independence Day observed on Friday the 3rd", () => {
  assert.deepEqual([...nyseHolidays(2026)].sort(), [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
  ]);
});

test("a Saturday New Year's Day isn't moved into the old year", () => {
  assert.ok(!nyseHolidays(2022).has("2021-12-31"));
  assert.ok(!nyseHolidays(2022).has("2022-01-01"));
});

test("2026 has 251 trading days (261 weekdays, 10 holidays)", () => {
  assert.equal(marketDays("2026-01-01", "2026-12-31").length, 251);
});

test("a week with a holiday", () => {
  assert.deepEqual(marketDays("2026-11-23", "2026-11-29"), ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27"]);
});
