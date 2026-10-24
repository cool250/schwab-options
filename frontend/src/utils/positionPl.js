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
