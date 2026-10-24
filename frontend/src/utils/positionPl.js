import { getMultiplier } from './contractMultiplier.js'

// Pure pricing for open positions — shared by the Positions page and
// Reports' unrealized total (utils/openPositions.js). No API calls, so it
// runs under `npm test`.

/** A futures-option row's unrealized P&L at `bids` ({ [contract symbol]: bid }),
 *  or null until its quote(s) are in. A grouped ratio-spread row is priced
 *  leg by leg. */
export function futuresOptionRowPl(row, bids) {
  const multiplier = row.multiplier ?? 100
  let currentValue = null
  if (row.long_leg && row.short_leg) {
    const longPrice = bids[row.long_leg.symbol]
    const shortPrice = bids[row.short_leg.symbol]
    if (longPrice != null && shortPrice != null) {
      currentValue = ((row.short_leg.amount * shortPrice) - (row.long_leg.amount * longPrice)) * multiplier
    }
  } else {
    const price = bids[row.symbol]
    if (price != null) currentValue = price * -(row.quantity ?? 0) * multiplier
  }
  return currentValue == null ? null : (row.total_value ?? 0) - currentValue
}

/** An outright futures row's unrealized P&L at `prices` ({ ES: 7712.25 }), or null. */
export function futuresRowPl(row, prices) {
  const price = prices[row.symbol]
  return price == null ? null : (price - row.trade_price) * row.quantity * getMultiplier(row.symbol)
}

/** The quote requests for every real futures-option contract in `rows` —
 *  both legs of a grouped ratio-spread row. */
export function futuresOptionContracts(puts, calls) {
  const contracts = []
  for (const [rows, type] of [[puts ?? [], 'PUT'], [calls ?? [], 'CALL']]) {
    for (const row of rows) {
      for (const leg of row.long_leg ? [row.long_leg, row.short_leg] : [row]) {
        contracts.push({ key: leg.symbol, underlying: `/${row.ticker}`, expiration: row.expiration_date, strike: leg.strike_price, type })
      }
    }
  }
  return contracts
}

/** A stock / ETF position's unrealized P&L at `basis`, the per-share price
 *  its own fills had (GET /portfolio/positions/stocks/trade-basis).
 *
 *  Schwab's average price for shares that came from an assignment already
 *  has the option's premium folded in (a QQQ short assigned at $610 shows
 *  at $654), and Reports counts that premium in realized option P&L too —
 *  so valuing the shares at Schwab's price would count it twice. Where the
 *  basis is unknown (null: bought before the history reaches), Schwab's
 *  own figure, `broker_pl`, is used. */
export function stockRowPl(stock, basis) {
  if (basis == null || stock.current_price == null) return stock.broker_pl ?? null
  return (stock.current_price - basis) * (stock.quantity ?? 0)
}
