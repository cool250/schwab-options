import { getMultiplier, MULTIPLIER } from './contractMultiplier.js'

/*
 * The Home page's decisions, as pure functions over the rows the Positions
 * endpoints return (and the Home rules in config/app.properties, home.*).
 * No API calls, so it runs under `npm test`. Dollar figures are plain
 * numbers; the page formats them.
 */

const DAY = 86400000
const isoToday = () => new Date().toISOString().slice(0, 10)
const daysBetween = (fromIso, toIso) => Math.round((Date.parse(`${toIso}T00:00:00Z`) - Date.parse(`${fromIso}T00:00:00Z`)) / DAY)

/** Estimated margin of outright futures: |qty| x price x point value x pct.
 *  Schwab doesn't report futures margin, so this stands in for it.
 *  futures: [{ symbol: 'ES', quantity, trade_price }]; prices: { ES: 7712.25 }. */
export function futuresMarginEstimate(futures, prices, pct) {
  let total = 0
  let unpriced = 0
  for (const f of futures ?? []) {
    const price = prices[f.symbol]
    if (price == null) { unpriced++; continue }
    total += Math.abs(f.quantity) * price * getMultiplier(f.symbol) * (pct / 100)
  }
  return { total, unpriced }
}

/** How many new short contracts on a root fit in `funds` at the margin
 *  estimate (pct of one contract's notional at `price`). */
export function contractsAffordable(funds, price, root, pct) {
  const perContract = price * getMultiplier(root) * (pct / 100)
  if (!funds || !perContract) return 0
  return Math.max(0, Math.floor(funds / perContract))
}

/** A futures-option idea's numbers per contract, with margin at pct of
 *  notional: { credit, margin, returnOnMargin (%), annualized (%) }. */
export function futuresIdeaNumbers(row, pct) {
  const mult = getMultiplier(row.underlying)
  const credit = row.premium * mult
  const notionalPrice = row.type === 'PUT' ? row.strike : row.spot
  const margin = notionalPrice * mult * (pct / 100)
  const returnOnMargin = margin ? (credit / margin) * 100 : null
  const annualized = returnOnMargin == null ? null : returnOnMargin * 365 / Math.max(row.dte ?? 1, 1)
  return { credit, margin, returnOnMargin, annualized }
}

/** Short option rows that have kept at least `pct` of their premium.
 *  rows: [{ ...row, pl, credit }] — pl the unrealized P&L, credit the
 *  premium taken in (both dollars). Sorted by percent kept, highest first. */
export function takeProfitCandidates(rows, pct) {
  return rows
    .filter((r) => r.credit > 0 && r.pl != null)
    .map((r) => ({ ...r, kept: (r.pl / r.credit) * 100 }))
    .filter((r) => r.kept >= pct)
    .sort((a, b) => b.kept - a.kept)
}

/** An equity option position row as a short-option entry for the rules
 *  above (null for a long): { ticker, type, strike, expiration, dte,
 *  quantity, underlyingPrice, credit, pl }. */
export function equityShort(row, type) {
  if (!(row.quantity < 0)) return null
  return {
    key: row.symbol,
    ticker: row.ticker,
    type,
    strike: row.strike_price,
    expiration: row.expiration_date,
    dte: row.days_to_expiry,
    quantity: row.quantity,
    underlyingPrice: row.underlying_price ?? null,
    credit: (row.trade_price ?? 0) * -row.quantity * MULTIPLIER,
    pl: row.total_value ?? null,
  }
}

/** Where a short stands against its strike: 'itm' past it, 'at_risk'
 *  within atRiskPct of it, 'otm' otherwise, null without a price.
 *  distance: percent the underlying is on the safe side of the strike. */
export function moneyness(short, atRiskPct) {
  const u = short.underlyingPrice
  if (u == null || !short.strike) return { status: null, distance: null }
  const distance = short.type === 'PUT' ? ((u - short.strike) / short.strike) * 100 : ((short.strike - u) / short.strike) * 100
  const status = distance < 0 ? 'itm' : distance < atRiskPct ? 'at_risk' : 'otm'
  return { status, distance }
}

/** Shorts expiring within `days`, each with its moneyness, the riskiest
 *  first (in the money, then at risk, then by days to expiry). */
export function expiringSoon(shorts, days, atRiskPct) {
  const rank = { itm: 0, at_risk: 1, otm: 2, null: 3 }
  return shorts
    .filter((s) => s.dte != null && s.dte <= days)
    .map((s) => ({ ...s, ...moneyness(s, atRiskPct) }))
    .sort((a, b) => rank[a.status] - rank[b.status] || a.dte - b.dte)
}

/** Shares not yet earning option premium: long shares beyond what short
 *  calls cover (sell covered calls), short shares beyond what short puts
 *  cover (sell covered puts). stocks: Positions' stock rows; puts/calls: its
 *  option rows. -> [{ ticker, side: 'CALL' | 'PUT', shares, contracts }]. */
export function uncoveredShares(stocks, puts, calls) {
  const shortContracts = (rows, ticker) => rows
    .filter((r) => r.ticker === ticker && r.quantity < 0)
    .reduce((s, r) => s - r.quantity, 0)
  const out = []
  for (const s of stocks ?? []) {
    const long = s.quantity > 0
    const covered = shortContracts(long ? calls : puts, s.symbol) * MULTIPLIER
    const free = Math.abs(s.quantity) - covered
    const contracts = Math.floor(free / MULTIPLIER)
    if (contracts > 0) out.push({ ticker: s.symbol, side: long ? 'CALL' : 'PUT', shares: free, contracts, price: s.current_price ?? null })
  }
  return out.sort((a, b) => b.contracts * (b.price ?? 0) - a.contracts * (a.price ?? 0))
}

/** Tickers whose exposure is above pct of net liquidation value. Exposure:
 *  the shares' market value plus short puts' strike value (what assignment
 *  would cost). -> [{ ticker, exposure, share }], largest first. */
export function concentration(stocks, puts, netLiq, pct) {
  if (!netLiq) return []
  const by = {}
  for (const s of stocks ?? []) by[s.symbol] = (by[s.symbol] ?? 0) + Math.abs(s.quantity * (s.current_price ?? 0))
  for (const p of puts ?? []) if (p.quantity < 0) by[p.ticker] = (by[p.ticker] ?? 0) + p.strike_price * MULTIPLIER * -p.quantity
  return Object.entries(by)
    .map(([ticker, exposure]) => ({ ticker, exposure, share: (exposure / netLiq) * 100 }))
    .filter((r) => r.share > pct)
    .sort((a, b) => b.exposure - a.exposure)
}

/** Open shorts by expiration date over the next `days` calendar days:
 *  [{ date, count, credit }] — credit the premium still at stake. */
export function expiryCalendar(shorts, days, today = isoToday()) {
  const by = {}
  for (const s of shorts) {
    if (!s.expiration) continue
    const ahead = daysBetween(today, s.expiration)
    if (ahead < 0 || ahead > days) continue
    const d = (by[s.expiration] ??= { date: s.expiration, count: 0, credit: 0 })
    d.count++
    d.credit += s.credit ?? 0
  }
  return Object.values(by).sort((a, b) => a.date.localeCompare(b.date))
}

/** How the margin cushion responds to a market-wide move (every
 *  underlying moving together by the same percent), to first order:
 *  exposures: [{ pnl, req }] per position — pnl the dollar P&L of a +100%
 *  move (shares: quantity x price; an option: delta x quantity x multiplier
 *  x underlying price; a future: its notional), req the margin requirement,
 *  which scales with the price. -> { pnl, req, net } summed, net = pnl - req:
 *  the cushion changes by net x move (move as a fraction, e.g. -0.05). */
export function marginSensitivity(exposures) {
  let pnl = 0
  let req = 0
  for (const e of exposures) { pnl += e.pnl ?? 0; req += e.req ?? 0 }
  return { pnl, req, net: pnl - req }
}

/** The cushion after `move` (a fraction): cushion + move x net. */
export const cushionAfter = (cushion, sensitivity, move) => cushion + move * sensitivity.net

/** The move (a fraction, signed: negative = a drop) at which the cushion
 *  reaches zero, or null if no move gets there (net is 0). Linear — a
 *  first-order estimate, least reliable for large moves. */
export function moveToMarginCall(cushion, sensitivity) {
  if (!sensitivity.net) return null
  return -cushion / sensitivity.net
}
