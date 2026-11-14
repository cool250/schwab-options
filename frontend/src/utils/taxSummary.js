import { isFuturesRoot } from './contractMultiplier.js'

/*
 * Reports' Tax summary tab: realized P&L split the way the tax forms split it.
 *   Section 1256 (Form 6781)  futures, futures options and broad-based index
 *                             options — 60% long-term / 40% short-term however
 *                             long they were held, and marked to market at
 *                             year end (open ones count at their value then).
 *   Everything else           equity options and shares (Form 8949 /
 *                             Schedule D) — long-term only when held more than
 *                             a year; a written option is short-term always.
 * Rows are the Reports page's closed trades: options { underlying_symbol,
 * open_type, date, close_date, total_amount }, equity & futures { symbol,
 * asset_type, date, close_date, total_amount }.
 */

// Broad-based index options are 1256 contracts too (SPY / QQQ options,
// on ETFs, are not). Schwab may prefix an index with "$".
export const INDEX_OPTION_ROOTS = new Set(['SPX', 'SPXW', 'XSP', 'NDX', 'NDXP', 'RUT', 'RUTW', 'VIX', 'VIXW', 'OEX', 'XEO', 'DJX'])

const root = (sym) => (sym ?? '').replace(/^[/$]/, '').toUpperCase()
export const isIndexOption = (t) => INDEX_OPTION_ROOTS.has(root(t.underlying_symbol))

/** Long-term: sold more than one year after it was bought — after the
 *  anniversary of the open date, not on it. */
export function isLongTerm(t) {
  if (!t.date || !t.close_date) return false
  const open = String(t.date).slice(0, 10)
  return String(t.close_date).slice(0, 10) > `${Number(open.slice(0, 4)) + 1}${open.slice(4)}`
}

// Estimated-tax payment periods (Form 1040-ES / 2210): uneven on purpose.
export const ESTIMATE_PERIODS = [
  { label: 'Jan 1 – Mar 31', months: [0, 2], due: 'Apr 15' },
  { label: 'Apr 1 – May 31', months: [3, 4], due: 'Jun 15' },
  { label: 'Jun 1 – Aug 31', months: [5, 7], due: 'Sep 15' },
  { label: 'Sep 1 – Dec 31', months: [8, 11], due: 'Jan 15' },
]

/**
 * The year's dividends, interest and fees (TransactionProvider
 * .fetch_income_and_fees, totalled by category — signed, money paid
 * negative), grouped by how a return treats them:
 *   deductible  margin interest and dividends paid on shares held short —
 *               Schedule C with trader tax status, else investment interest
 *               (Form 4952); shown as positive expenses
 *   inBasis     commissions and exchange / regulatory fees — already in the
 *               1099-B's proceeds and cost, so not deducted again
 *   income      interest and dividends received (1099-INT / 1099-DIV)
 * Each a list of { label, amount } with a non-zero amount, plus its total.
 */
export function incomeExpenseGroups(incomeBy = {}, feesBy = {}) {
  const lines = (byCategory, defs, sign = 1) => {
    const named = new Set(defs.flatMap((d) => d.categories ?? []))
    return defs
      .map((d) => {
        const cats = d.rest ? Object.keys(byCategory).filter((c) => !named.has(c)) : d.categories
        return { label: d.label, amount: sign * cats.reduce((s, c) => s + (byCategory[c] ?? 0), 0) }
      })
      .filter((l) => l.amount)
  }
  const group = (items) => ({ items, total: items.reduce((s, l) => s + l.amount, 0) })
  return {
    deductible: group(lines(incomeBy, [
      { label: 'Margin interest', categories: ['MARGIN_INTEREST'] },
      { label: 'Dividends paid on short shares', categories: ['SHORT_DIVIDEND'] },
    ], -1)),
    inBasis: group(lines(feesBy, [
      { label: 'Commissions', categories: ['COMMISSION'] },
      { label: 'Exchange & regulatory fees', rest: true },
    ], -1)),
    income: group(lines(incomeBy, [
      { label: 'Interest on cash', categories: ['INTEREST'] },
      { label: 'Money-fund dividends', categories: ['MONEY_FUND_DIVIDEND'] },
      { label: 'Dividends', categories: ['DIVIDEND'] },
    ])),
  }
}

// Top marginal rates for 2026: federal 37% on ordinary income and short-term
// gains, 20% on long-term gains, the 3.8% net investment income tax, and
// California's 13.3% (12.3% plus the 1% mental health services tax over $1M),
// which taxes every gain as ordinary income.
export const TOP_TAX_RATES = { federalOrdinary: 0.37, federalLongTerm: 0.2, niit: 0.038, california: 0.133 }

/**
 * Estimated tax on the year's trading as if all of it fell in the top
 * brackets — no other income, deductions or credits.
 *   s1256, other   taxSummary()'s, with 1256 already split 60/40
 *   income         interest and dividends received (taxed as ordinary —
 *                  qualified dividends would be 20%)
 *   deductible     margin interest and short dividends, taken from ordinary
 *                  income (investment interest only up to that income)
 *   fees           commissions and fees, which the 1099-B takes out of
 *                  proceeds and cost: taken from the short-term gains
 * Short- and long-term gains net against each other first; a net capital
 * loss is taxed at nothing and returned as capitalLoss (negative — only
 * $3,000 of it is deductible a year, the rest carries forward).
 * → { shortTerm, longTerm, ordinary, taxable, capitalLoss,
 *     federal: { ordinary, longTerm, niit, total }, state, total, effective }
 */
export function estimatedTax({ s1256, other, income = 0, deductible = 0, fees = 0 }, rates = TOP_TAX_RATES) {
  let st = s1256.shortTerm + other.shortTerm - fees
  let lt = s1256.longTerm + other.longTerm
  if (st < 0 && lt > 0) { lt += st; st = 0 } else if (lt < 0 && st > 0) { st += lt; lt = 0 }
  const capitalLoss = Math.min(0, st) + Math.min(0, lt)
  st = Math.max(0, st)
  lt = Math.max(0, lt)
  const ordinary = Math.max(0, st + income - deductible)
  const taxable = ordinary + lt
  const federal = {
    ordinary: ordinary * rates.federalOrdinary,
    longTerm: lt * rates.federalLongTerm,
    niit: taxable * rates.niit,
  }
  federal.total = federal.ordinary + federal.longTerm + federal.niit
  const state = taxable * rates.california
  const total = federal.total + state
  return { shortTerm: st, longTerm: lt, ordinary, taxable, capitalLoss, federal, state, total, effective: taxable ? total / taxable : 0 }
}

/**
 * optionTrades / equityTrades: the year's closed trades. open1256: unrealized
 * P&L of the 1256 positions open now (futures and futures options), or null
 * when it isn't known. lastMonth: last month shown (0-based) — periods that
 * haven't started are left out.
 * → { s1256: { futuresOptions, indexOptions, futures, realized, open, total,
 *     longTerm, shortTerm },
 *     other: { equityOptions: { short, long }, stocks: { short, long },
 *     shortTerm, longTerm },
 *     periods: [{ label, due, s1256, shortTerm, longTerm, total }] }
 * s1256.total includes `open` when it's known; the periods are realized only.
 */
export function taxSummary({ optionTrades = [], equityTrades = [], open1256 = null, lastMonth = 11 }) {
  const s = { futuresOptions: 0, indexOptions: 0, futures: 0 }
  const other = { equityOptions: { short: 0, long: 0 }, stocks: { short: 0, long: 0 } }
  const periods = ESTIMATE_PERIODS
    .filter((p) => p.months[0] <= lastMonth)
    .map((p) => ({ label: p.label, due: p.due, months: p.months, s1256: 0, shortTerm: 0, longTerm: 0 }))
  const periodOf = (t) => {
    const m = Number(String(t.close_date).slice(5, 7)) - 1
    return periods.find((p) => m >= p.months[0] && m <= p.months[1])
  }
  const add = (t, bucket, column) => {
    const v = t.total_amount ?? 0
    bucket.target[bucket.key] += v
    const p = periodOf(t)
    if (p) p[column] += v
  }

  for (const t of optionTrades) {
    if (isFuturesRoot(t.underlying_symbol)) add(t, { target: s, key: 'futuresOptions' }, 's1256')
    else if (isIndexOption(t)) add(t, { target: s, key: 'indexOptions' }, 's1256')
    else {
      // A written option's gain or loss is short-term however long it was open.
      const long = t.open_type !== 'STO' && isLongTerm(t)
      add(t, { target: other.equityOptions, key: long ? 'long' : 'short' }, long ? 'longTerm' : 'shortTerm')
    }
  }
  for (const t of equityTrades) {
    if (t.asset_type === 'FUTURE') add(t, { target: s, key: 'futures' }, 's1256')
    else {
      const long = isLongTerm(t)
      add(t, { target: other.stocks, key: long ? 'long' : 'short' }, long ? 'longTerm' : 'shortTerm')
    }
  }

  const realized = s.futuresOptions + s.indexOptions + s.futures
  const total = realized + (open1256 ?? 0)
  return {
    s1256: { ...s, realized, open: open1256, total, longTerm: total * 0.6, shortTerm: total * 0.4 },
    other: {
      ...other,
      shortTerm: other.equityOptions.short + other.stocks.short,
      longTerm: other.equityOptions.long + other.stocks.long,
    },
    periods: periods.map(({ months: _, ...p }) => ({ ...p, total: p.s1256 + p.shortTerm + p.longTerm })),
  }
}
