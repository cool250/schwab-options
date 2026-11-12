// NYSE trading days, for "days traded out of market days" (Reports' Trade
// Details). Full-day closures only, by the exchange's standing rules: a
// Saturday holiday is observed the Friday before (except New Year's Day,
// which isn't moved into the old year), a Sunday one the Monday after.
// Dates are "YYYY-MM-DD" calendar dates, no time zone.

const iso = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
const dow = (y, m, d) => new Date(Date.UTC(y, m - 1, d)).getUTCDay()

/** The nth (1-based) weekday (0 = Sunday) of a month; n = -1: the last. */
function nthWeekday(y, m, weekday, n) {
  if (n > 0) {
    const first = dow(y, m, 1)
    return iso(y, m, 1 + ((weekday - first + 7) % 7) + (n - 1) * 7)
  }
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return iso(y, m, last - ((dow(y, m, last) - weekday + 7) % 7))
}

function observed(y, m, d, { moveSaturday = true } = {}) {
  const day = dow(y, m, d)
  if (day === 6) return moveSaturday ? iso(...shift(y, m, d, -1)) : null
  if (day === 0) return iso(...shift(y, m, d, 1))
  return iso(y, m, d)
}

function shift(y, m, d, n) {
  const t = new Date(Date.UTC(y, m - 1, d + n))
  return [t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()]
}

/** Easter Sunday (Anonymous Gregorian algorithm) as [month, day]. */
function easter(y) {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451)
  return [Math.floor((h + l - 7 * m + 114) / 31), ((h + l - 7 * m + 114) % 31) + 1]
}

/** The year's NYSE full-day holidays, as a Set of dates. */
export function nyseHolidays(y) {
  const [em, ed] = easter(y)
  return new Set([
    observed(y, 1, 1, { moveSaturday: false }),
    nthWeekday(y, 1, 1, 3),           // Martin Luther King Jr. Day
    nthWeekday(y, 2, 1, 3),           // Washington's Birthday
    iso(...shift(y, em, ed, -2)),     // Good Friday
    nthWeekday(y, 5, 1, -1),          // Memorial Day
    y >= 2022 ? observed(y, 6, 19) : null, // Juneteenth
    observed(y, 7, 4),
    nthWeekday(y, 9, 1, 1),           // Labor Day
    nthWeekday(y, 11, 4, 4),          // Thanksgiving
    observed(y, 12, 25),
  ].filter(Boolean))
}

/** Market (trading) days from start to end, inclusive. */
export function marketDays(start, end) {
  const out = []
  const holidays = new Map()
  for (let t = new Date(`${start}T00:00:00Z`); t <= new Date(`${end}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + 1)) {
    const day = t.getUTCDay()
    if (day === 0 || day === 6) continue
    const y = t.getUTCFullYear()
    if (!holidays.has(y)) holidays.set(y, nyseHolidays(y))
    const d = t.toISOString().slice(0, 10)
    if (!holidays.get(y).has(d)) out.push(d)
  }
  return out
}
