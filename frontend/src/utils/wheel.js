import { getMultiplier } from './contractMultiplier.js'

// The options-wheel rules in the browser, for Home's New Income ideas — the
// same as copilot/wheel.py (the copilot's get_wheel_snapshot), checked
// against the shared tests/fixtures/wheel_cases.json by wheel.test.js, so a
// change to one that the other doesn't follow fails a test. Rows are the
// API's own shapes (snake_case). Pure functions: no API calls.

const EQUITY_MULTIPLIER = 100

const root = (symbol) => symbol.replace(/^\//, '').toUpperCase()

/** (strike, signed contracts) per leg — a grouped ratio-spread row has a
 *  long and a short leg (unsigned amounts) instead of strike/quantity. */
function optionLegs(row) {
  if (row.long_leg && row.short_leg) {
    return [[row.long_leg.strike_price, row.long_leg.amount], [row.short_leg.strike_price, -row.short_leg.amount]]
  }
  return [[row.strike_price, row.quantity]]
}

/** Full contract value per underlying, split by kind — see
 *  notional_by_underlying in copilot/wheel.py. */
export function notionalByUnderlying({ stocks = [], equityPuts = [], futures = [], futuresOptionPuts = [] }) {
  const by = {}
  const add = (underlying, kind, value) => {
    const entry = (by[underlying] ??= { stock: 0, futures: 0, short_puts: 0, total: 0, unpriced: 0 })
    if (value == null) { entry.unpriced += 1; return }
    entry[kind] += value
    entry.total += value
  }
  for (const s of stocks) {
    add(s.symbol, 'stock', s.current_price == null ? null : Math.abs(s.quantity) * s.current_price)
  }
  for (const f of futures) {
    const r = root(f.symbol)
    add(`/${r}`, 'futures', f.current_price == null ? null : Math.abs(f.quantity) * f.current_price * getMultiplier(r))
  }
  for (const p of equityPuts) {
    if (p.quantity < 0) add(p.ticker, 'short_puts', p.strike_price * -p.quantity * EQUITY_MULTIPLIER)
  }
  for (const p of futuresOptionPuts) {
    const r = root(p.ticker)
    for (const [strike, qty] of optionLegs(p)) {
      // The point value (/ES 50, /NQ 20), never the equity 100.
      if (qty < 0) add(`/${r}`, 'short_puts', strike * -qty * (p.multiplier || getMultiplier(r)))
    }
  }
  return by
}

/** Per underlying: short calls, what covers them, and how many more short
 *  calls stay covered — see call_coverage in copilot/wheel.py. A long call
 *  counts as cover only if it expires on or after the latest short call. */
export function callCoverage({ stocks = [], equityCalls = [], futures = [], futuresOptionCalls = [] }) {
  const by = {}
  const entry = (u) => (by[u] ??= { shareLots: 0, longFutures: 0, longCalls: [], shortCalls: [] })
  for (const s of stocks) if (s.quantity > 0) entry(s.symbol).shareLots += Math.floor(s.quantity / EQUITY_MULTIPLIER)
  for (const f of futures) if (f.quantity > 0) entry(`/${root(f.symbol)}`).longFutures += f.quantity
  for (const [rows, isFutures] of [[equityCalls, false], [futuresOptionCalls, true]]) {
    for (const c of rows) {
      const underlying = isFutures ? `/${root(c.ticker)}` : c.ticker
      for (const [, qty] of optionLegs(c)) {
        entry(underlying)[qty > 0 ? 'longCalls' : 'shortCalls'].push([Math.abs(qty), c.expiration_date ?? ''])
      }
    }
  }
  const result = {}
  for (const [underlying, e] of Object.entries(by)) {
    const short = e.shortCalls.reduce((s, [q]) => s + q, 0)
    const latestShort = e.shortCalls.reduce((m, [, exp]) => (exp > m ? exp : m), '')
    const longCover = e.longCalls.reduce((s, [q, exp]) => s + (exp >= latestShort ? q : 0), 0)
    const cover = e.shareLots + e.longFutures + longCover
    result[underlying] = {
      short_calls: short,
      covered_by: { share_lots: e.shareLots, long_futures: e.longFutures, long_calls: longCover },
      free_cover: Math.max(0, cover - short),
      naked: Math.max(0, short - cover),
    }
  }
  return result
}

export function riskMode(leveragePct, aggressiveMaxPct, defensiveMinPct) {
  if (leveragePct == null) return null
  if (leveragePct < aggressiveMaxPct) return 'aggressive'
  return leveragePct >= defensiveMinPct ? 'defensive' : 'neutral'
}

/** Delta ranges (hundredths, [low, high]) for new short puts and calls in
 *  `mode`; puts null in defensive mode, both null without a mode. */
export function deltaBands(mode, rules) {
  if (mode == null) return { put: null, call: null }
  return {
    put: mode === 'defensive' ? null : rules[`wheel.${mode}_put_delta_pct`],
    call: rules[`wheel.${mode}_call_delta_pct`],
  }
}

/** Leverage, mode, delta ranges and call coverage for the book — the
 *  part of the copilot's snapshot New Income needs. */
export function wheelSnapshot({ netLiquidity, stocks, equityPuts, equityCalls, futures, futuresOptionPuts, futuresOptionCalls, rules }) {
  const notional = notionalByUnderlying({ stocks, equityPuts, futures, futuresOptionPuts })
  const total = Object.values(notional).reduce((s, n) => s + n.total, 0)
  const leveragePct = !netLiquidity || netLiquidity <= 0 ? null : Math.round((total / netLiquidity) * 1000) / 10
  const aggressiveBelow = rules['wheel.aggressive_max_leverage_pct']
  const defensiveFrom = Math.max(rules['wheel.defensive_min_leverage_pct'], aggressiveBelow)
  const mode = riskMode(leveragePct, aggressiveBelow, defensiveFrom)
  return {
    netLiquidity,
    notionalTotal: total,
    unpriced: Object.values(notional).reduce((s, n) => s + n.unpriced, 0),
    leveragePct,
    mode,
    bands: { aggressiveBelow, defensiveFrom },
    deltaBands: deltaBands(mode, rules),
    coverage: callCoverage({ stocks, equityCalls, futures, futuresOptionCalls }),
  }
}

/** Leverage (percent) after adding `notional` dollars. */
export function leverageAfter(snapshot, notional) {
  return snapshot.leveragePct == null ? null : ((snapshot.notionalTotal + notional) / snapshot.netLiquidity) * 100
}

/** The most new short puts at `strike` that keep leverage below the
 *  defensive band — the playbook's sizing limit. */
export function putsUnderLeverage(snapshot, strike, multiplier) {
  if (snapshot.leveragePct == null) return 0
  const room = (snapshot.bands.defensiveFrom / 100) * snapshot.netLiquidity - snapshot.notionalTotal
  const each = strike * multiplier
  // Strictly below the band: the last contract mustn't land exactly on it.
  return room <= 0 ? 0 : Math.max(0, Math.ceil(room / each) - 1)
}

/** The futures lots (one entry per contract, oldest first) a new short call
 *  would cover: existing short calls use the oldest lots first, net of the
 *  long calls that cover them. -> [{ date, entry }] */
export function freeLots(futuresRow, coverage) {
  const units = []
  for (const lot of [...(futuresRow?.lots ?? [])].sort((a, b) => a.date.localeCompare(b.date))) {
    for (let i = 0; i < lot.quantity; i++) units.push({ date: lot.date, entry: lot.trade_price })
  }
  const used = coverage ? Math.max(0, coverage.short_calls - coverage.covered_by.long_calls) : 0
  return units.slice(used)
}

/** A covered call's result if it's assigned against `lot`: the future is
 *  delivered at the strike, so (strike − lot entry) × point value plus the
 *  credit, per contract. Negative = locks in a loss on that lot. */
export function assignedResult(strike, credit, lot, multiplier) {
  return lot == null ? null : (strike - lot.entry) * multiplier + credit
}
