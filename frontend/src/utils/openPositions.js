import { getPositions, getFuturesPosition, getFuturesOptionPosition, getMarketQuotes, getOptionBids } from '../api/client'
import { futuresOptionContracts, futuresOptionRowPl, futuresRowPl } from './positionPl'

/*
 * Unrealized P&L of the positions open right now, valued the way the
 * Positions page values them — shared so the two can't drift apart:
 *   stocks / ETFs     Schwab's own unrealized P&L (broker_pl)
 *   equity options    total_value, priced at live quotes on the backend
 *   futures options   entry value (total_value) minus the position re-priced
 *                     at the live bid (futuresOptionRowPl)
 *   outright futures  (live price - entry) x quantity x point value
 * Each is "since the position was opened", not since the start of the year.
 */

// Sum of the priced values; how many couldn't be priced.
function sumPriced(values) {
  const priced = values.filter((v) => v != null)
  return { pl: priced.reduce((s, v) => s + v, 0), unpriced: values.length - priced.length }
}

/**
 * Unrealized P&L of every open position, loaded fresh (never cached —
 * account data). Resolves to { total, stocks, options, futures, unpriced,
 * futuresMissing }: each part a dollar figure over what could be priced —
 * `options` covers equity and futures options, `futures` the outright
 * contracts only (as the Positions page's Futures table); `unpriced` counts
 * the positions left out for want of a quote; `futuresMissing` is true when
 * the futures or futures-option positions couldn't be loaded, so the total
 * leaves them out.
 */
export async function loadOpenPositionsPl() {
  const [positions, futures, futuresOptions] = await Promise.all([
    getPositions(),
    getFuturesPosition().catch(() => null),
    getFuturesOptionPosition().catch(() => null),
  ])
  const stocks = sumPriced((positions.stocks ?? []).map((s) => s.broker_pl ?? null))

  const futuresMissing = futures == null || futuresOptions == null
  const roots = (futures ?? []).map((f) => f.symbol).filter(Boolean)
  const contracts = futuresOptions ? futuresOptionContracts(futuresOptions.puts, futuresOptions.calls) : []
  const [prices, bids] = await Promise.all([
    roots.length ? getMarketQuotes({ futures: roots }).then((q) => q.futures ?? {}).catch(() => ({})) : {},
    getOptionBids(contracts).catch(() => ({})),
  ])
  const options = sumPriced([
    ...[...(positions.puts ?? []), ...(positions.calls ?? [])].map((o) => o.total_value ?? null),
    ...[...(futuresOptions?.puts ?? []), ...(futuresOptions?.calls ?? [])].map((r) => futuresOptionRowPl(r, bids)),
  ])
  const fut = sumPriced((futures ?? []).map((f) => futuresRowPl(f, prices)))

  return {
    total: stocks.pl + options.pl + fut.pl,
    stocks: stocks.pl,
    options: options.pl,
    futures: fut.pl,
    unpriced: stocks.unpriced + options.unpriced + fut.unpriced,
    futuresMissing,
  }
}
