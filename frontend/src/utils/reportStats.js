// Pure calculations behind the Reports page (pages/Reports.jsx and
// components/ReportViews.jsx). Rows are transaction rows as the page has
// already normalized them: { underlying_symbol | symbol, close_date
// ("YYYY-MM-DD"), total_amount, type }.

export const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const symbolOf = (row) => row.underlying_symbol ?? row.symbol ?? 'OTHER'

/** Rows that are realized trades: closed in the period. Still-open option
 *  legs (Schwab's raw "TRADE" type — zeroed by normalizeOptionRows) and
 *  rows without a close date aren't trades to count yet. */
export function closedTrades(rows, { dropZero = false } = {}) {
  return rows.filter((r) => r.close_date && r.type !== 'TRADE' && (!dropZero || r.total_amount))
}

/** Net, trade count and win rate.
 *  A trade closed at exactly $0 counts as a trade but neither a win nor a loss.
 *
 *  ASSIGNED equity options and EXERCISED futures options (both counted as
 *  `exercised` here) count toward net P&L (their premium is real, and the
 *  delivered shares / future are booked at the strike) but not toward win
 *  rate: the option's own result is just its premium, and how the trade
 *  actually ended shows up in the shares' or future's P&L instead — scoring
 *  a short that was assigned against you as a full win would flatter it. */
export function tradeStats(trades) {
  let net = 0, wins = 0, decided = 0, exercised = 0, exercisedNet = 0, expired = 0
  for (const t of trades) {
    const v = t.total_amount ?? 0
    net += v
    if (t.type === 'EXERCISED' || t.type === 'ASSIGNED') { exercised++; exercisedNet += v; continue }
    if (t.type === 'EXPIRED') expired++
    decided++
    if (v > 0) wins++
  }
  return {
    net,
    n: trades.length,
    // n = closed + expired + exercised (closed: bought/sold back before expiry)
    closed: decided - expired,
    expired,
    wins,
    decided,
    exercised,
    exercisedNet,
    winRate: decided ? wins / decided : null,
  }
}

/** Open (still-unrealized) trades, as the page annotates them: each
 *  { expiration: "YYYY-MM-DD", unrealized: number | null, atExpiry?: number }
 *  — unrealized is null while its live quote is loading or when it couldn't
 *  be priced. The total covers the priced ones; `unpriced` says how many it
 *  leaves out. atExpiry: P&L if every leg expires worthless (all of them,
 *  priced or not). */
export function openTradeStats(legs) {
  const priced = legs.filter((l) => l.unrealized != null)
  return {
    n: legs.length,
    unrealized: priced.length ? priced.reduce((s, l) => s + l.unrealized, 0) : null,
    unpriced: legs.length - priced.length,
    // null when no leg carries it (e.g. an unknown entry price), not a misleading $0.
    atExpiry: legs.some((l) => Number.isFinite(l.atExpiry))
      ? legs.reduce((s, l) => s + (Number.isFinite(l.atExpiry) ? l.atExpiry : 0), 0)
      : null,
  }
}

/** Map of key -> summed total_amount. */
export function sumBy(rows, keyOf) {
  const m = new Map()
  for (const r of rows) {
    const k = keyOf(r)
    m.set(k, (m.get(k) ?? 0) + (r.total_amount ?? 0))
  }
  return m
}

export function countBy(rows, keyOf) {
  const m = new Map()
  for (const r of rows) {
    const k = keyOf(r)
    m.set(k, (m.get(k) ?? 0) + 1)
  }
  return m
}

/** Per-symbol stats, best net first. */
export function symbolBreakdown(trades) {
  const groups = new Map()
  for (const t of trades) {
    const s = symbolOf(t)
    if (!groups.has(s)) groups.set(s, [])
    groups.get(s).push(t)
  }
  const rows = [...groups.entries()].map(([symbol, list]) => ({ symbol, ...tradeStats(list) }))
  const grossGains = rows.reduce((s, r) => s + (r.net > 0 ? r.net : 0), 0)
  for (const r of rows) r.shareOfGains = r.net > 0 && grossGains ? r.net / grossGains : null
  return rows.sort((a, b) => b.net - a.net)
}

/** Running total per trading day, in date order: [{ date, day, total }]. */
export function runningTotal(trades) {
  const daily = sumBy(trades, (t) => t.close_date)
  let run = 0
  return [...daily.keys()].sort().map((date) => {
    run += daily.get(date)
    return { date, day: daily.get(date), total: run }
  })
}

/** Trade Details: the trades the account holder placed, month by month —
 *  trades: GET /portfolio/transactions/placed-trades `trades` (one row per
 *  executed leg: { date, order_id, asset_class, position_effect }).
 *  closedTrades: the period's realized trades (an open `date` and a
 *  `close_date`), for the holding period. marketDays: the period's trading
 *  days ("YYYY-MM-DD", utils/marketCalendar.js). lastMonth: last month
 *  shown (0-based).
 *  → { months: [{ m, label, trades, orders, opening, closing, options,
 *  futures, stocks, daysTraded, marketDays }], total: same fields,
 *  holding: { avg, median, n } | null } */
export function placedTradeStats({ trades = [], closedTrades = [], marketDays = [], lastMonth = 11 }) {
  const blank = () => ({ trades: 0, orders: new Set(), opening: 0, closing: 0, options: 0, futures: 0, stocks: 0, days: new Set(), marketDays: 0 })
  const months = MONTH_NAMES.slice(0, lastMonth + 1).map(() => blank())
  const total = blank()
  const monthOf = (iso) => months[Number(iso.slice(5, 7)) - 1]
  for (const t of trades) {
    const row = monthOf(t.date)
    if (!row) continue
    for (const r of [row, total]) {
      r.trades++
      // An order's legs share its id; one without an id counts on its own.
      r.orders.add(t.order_id ?? `${t.date}-${r.trades}`)
      if (t.position_effect === 'OPENING') r.opening++
      else if (t.position_effect === 'CLOSING') r.closing++
      r[t.asset_class === 'OPTION' ? 'options' : t.asset_class === 'FUTURE' ? 'futures' : 'stocks']++
      r.days.add(t.date)
    }
  }
  for (const d of marketDays) {
    const row = monthOf(d)
    if (row) { row.marketDays++; total.marketDays++ }
  }
  const flat = (r, extra) => ({
    ...extra, trades: r.trades, orders: r.orders.size, opening: r.opening, closing: r.closing,
    options: r.options, futures: r.futures, stocks: r.stocks, daysTraded: r.days.size, marketDays: r.marketDays,
  })
  const held = closedTrades
    .filter((t) => t.date && t.close_date)
    .map((t) => Math.max(0, Math.round((utcDate(String(t.close_date).slice(0, 10)) - utcDate(String(t.date).slice(0, 10))) / 86400000)))
    .sort((a, b) => a - b)
  return {
    months: months.map((r, m) => flat(r, { m, label: MONTH_NAMES[m] })),
    total: flat(total),
    holding: held.length
      ? { avg: held.reduce((s, d) => s + d, 0) / held.length, median: held[Math.floor((held.length - 1) / 2)], n: held.length }
      : null,
  }
}

/** Diverging step (1-4 per side) by share of the largest magnitude — the
 *  P&L heat colors in tokens.css (--pnl-gain-N / --pnl-loss-N). */
export function pnlStep(value, maxAbs) {
  if (!value || !maxAbs) return null
  const r = Math.abs(value) / maxAbs
  const n = r < 0.25 ? 1 : r < 0.5 ? 2 : r < 0.75 ? 3 : 4
  return { background: `var(--pnl-${value > 0 ? 'gain' : 'loss'}-${n})`, color: `var(--pnl-on-${n})` }
}

// ---- Dates (all "YYYY-MM-DD", calendar dates with no time zone) ----

export const isoDate = (d) => d.toISOString().slice(0, 10)
export const utcDate = (iso) => new Date(`${iso}T00:00:00Z`)
export const addDays = (iso, n) => isoDate(new Date(utcDate(iso).getTime() + n * 86400000))
/** Monday of the week holding `iso`. */
export const mondayOf = (iso) => addDays(iso, -((utcDate(iso).getUTCDay() + 6) % 7))
export const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
export const longDate = (iso) =>
  utcDate(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })

// ---- Money ----

export function usd(v, decimals = 0) {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return `${v < 0 ? '−' : ''}$${s}`
}
export const signedUsd = (v) => (v > 0 ? `+${usd(v)}` : usd(v))
export function compactUsd(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  const s = a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : a >= 1000 ? `$${(a / 1000).toFixed(a >= 10000 ? 0 : 1)}K` : `$${Math.round(a)}`
  return `${v < 0 ? '−' : ''}${s}`
}
export const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
export const signClass = (v) => (v > 0 ? 'pnl-up' : v < 0 ? 'pnl-down' : '')
