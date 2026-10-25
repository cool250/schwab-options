import { getMultiplier, MULTIPLIER } from './contractMultiplier.js'
import { blackScholes } from './payoffMath.js'

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

/*
 * Margin cushion stress test: the whole book revalued after every
 * underlying moves together by `move` (a fraction, -0.10 = a 10% drop).
 * Deliberately cautious — it is there to warn before a margin call:
 *   - options are repriced in full (Black-Scholes at their implied
 *     volatility), not by delta, so a short option's loss speeds up;
 *   - a drop raises every option's volatility by ivRise points per 10%
 *     (a rally leaves it unchanged — no relief for shorts);
 *   - a short option's requirement follows the usual naked-option formula
 *     (greater of 20% of the underlying less the out-of-the-money amount,
 *     or 10% of the strike for a put / of the underlying for a call, plus
 *     the premium), scaled to what the broker reports for it today;
 *   - futures and futures options are margined per root like SPAN: the
 *     worst loss over a +/-futuresPct move, recomputed after the move;
 *   - no requirement is assumed to fall, so a move never frees margin.
 *
 * A stress position:
 *   { kind: 'stock', qty (shares, signed), price, req }
 *   { kind: 'future', root, qty (contracts, signed), price, mult }
 *   { kind: 'option', root (a futures root, or null for equity), type,
 *     strike, dte, qty (contracts, signed), mult, spot, iv, mid, delta, req }
 * An option without iv has it implied from mid; with neither it falls back
 * to delta; with none of them it is left out (and counted by the caller).
 */

const SCAN_STEPS = [-1, -2 / 3, -1 / 3, 1 / 3, 2 / 3, 1]

/** Implied volatility from an option price (bisection), null if the price
 *  is below intrinsic or out of reach. */
export function impliedVol(price, spot, strike, dte, type) {
  if (!(price > 0) || !(spot > 0) || !(strike > 0)) return null
  const isCall = type === 'CALL'
  const intrinsic = isCall ? Math.max(0, spot - strike) : Math.max(0, strike - spot)
  if (price <= intrinsic) return null
  let lo = 0.001, hi = 5
  if (blackScholes(spot, strike, dte, hi, isCall) < price) return null
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    if (blackScholes(spot, strike, dte, mid, isCall) < price) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

/** Volatility after a move: up ivRise points per 10% drop, unchanged on a
 *  rally. */
export const ivAfter = (iv, move, ivRise) => (move < 0 ? iv + (-move / 0.10) * (ivRise / 100) : iv)

/** The usual naked short option requirement, per share. */
export function shortOptionRequirement(type, strike, spot, premium) {
  const otm = type === 'PUT' ? Math.max(0, spot - strike) : Math.max(0, strike - spot)
  return Math.max(0.2 * spot - otm, 0.1 * (type === 'PUT' ? strike : spot)) + premium
}

// An option's value per share after `move`, or null if it can't be priced.
function optionValue(p, move, ivRise) {
  if (!p.iv) return null
  return blackScholes(p.spot * (1 + move), p.strike, p.dte ?? 0, ivAfter(p.iv, move, ivRise), p.type === 'CALL')
}

// An option's P&L (dollars) from today to `move`.
function optionPnl(p, move, ivRise) {
  const now = optionValue(p, 0, ivRise)
  const after = optionValue(p, move, ivRise)
  if (now != null) return (after - now) * p.qty * p.mult
  return p.delta * p.qty * p.mult * p.spot * move
}

/** The book as the stress test uses it: options given an iv (implied from
 *  mid where the quote had none), unpriceable positions split out. */
export function stressBook(positions) {
  const priced = []
  let unpriced = 0
  for (const p of positions) {
    if (p.kind !== 'option') {
      if (p.price == null) unpriced++
      else priced.push(p)
      continue
    }
    if (p.spot == null) { unpriced++; continue }
    const iv = p.iv || impliedVol(p.mid, p.spot, p.strike, p.dte ?? 0, p.type)
    if (!iv && p.delta == null) { unpriced++; continue }
    priced.push({ ...p, iv })
  }
  return { positions: priced, unpriced }
}

// Futures and futures options on one root: the worst loss over a
// +/-futuresPct scan starting from `move` (SPAN-like).
function rootRequirement(group, move, futuresPct, ivRise) {
  let worst = 0
  for (const step of SCAN_STEPS) {
    const scan = step * (futuresPct / 100)
    // Moving from (1 + move) to (1 + move)(1 + scan) = 1 + total.
    const total = (1 + move) * (1 + scan) - 1
    let pnl = 0
    for (const p of group) {
      if (p.kind === 'future') pnl += p.qty * p.price * p.mult * (total - move)
      else pnl += optionPnl(p, total, ivRise) - optionPnl(p, move, ivRise)
    }
    worst = Math.max(worst, -pnl)
  }
  return worst
}

/** The change in the cushion after `move`: P&L less any rise in margin
 *  requirement. -> { pnl, reqRise, change }. */
export function cushionChange(book, move, { futuresPct, ivRise }) {
  let pnl = 0
  let reqRise = 0
  const roots = {}
  for (const p of book.positions) {
    if (p.kind === 'stock') {
      pnl += p.qty * p.price * move
      reqRise += Math.max(0, (p.req ?? 0) * move)
    } else if (p.kind === 'future') {
      pnl += p.qty * p.price * p.mult * move
      ;(roots[p.root] ??= []).push(p)
    } else {
      pnl += optionPnl(p, move, ivRise)
      if (p.root) { (roots[p.root] ??= []).push(p); continue }
      if (!(p.qty < 0) || !p.req) continue
      const value = (m) => (p.iv ? optionValue(p, m, ivRise) : Math.max(0, p.mid ?? 0))
      const now = shortOptionRequirement(p.type, p.strike, p.spot, value(0))
      const after = shortOptionRequirement(p.type, p.strike, p.spot * (1 + move), value(move))
      if (now > 0) reqRise += Math.max(0, p.req * (after / now - 1))
    }
  }
  for (const group of Object.values(roots)) {
    reqRise += Math.max(0, rootRequirement(group, move, futuresPct, ivRise) - rootRequirement(group, 0, futuresPct, ivRise))
  }
  return { pnl, reqRise, change: pnl - reqRise }
}

/** The smallest move in `direction` (-1 a drop, +1 a rally) that takes the
 *  cushion to zero, searched in 0.5% steps up to `limit` and refined; null
 *  if the cushion holds that far. */
export function marginCallMove(cushion, book, direction, options, limit = 0.6) {
  const left = (m) => cushion + cushionChange(book, m, options).change
  if (left(0) <= 0) return 0
  let prev = 0
  for (let m = 0.005; m <= limit + 1e-9; m += 0.005) {
    const move = direction * m
    if (left(move) <= 0) {
      let lo = prev, hi = move
      for (let i = 0; i < 30; i++) {
        const mid = (lo + hi) / 2
        if (left(mid) <= 0) hi = mid
        else lo = mid
      }
      return hi
    }
    prev = move
  }
  return null
}
