import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getAppConfig, getPositions, getFuturesPosition, getFuturesOptionPosition, getMarketQuotes, getOptionQuotes,
  getAllocations, getEquityTransactions, getIncomeAndFees, screenOptions, friendlyErrorMessage,
} from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'
import { money, count } from '../utils/numberFormat'
import { formatDate } from '../utils/dateFormat'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { closedTrades } from '../utils/reportStats'
import { futuresOptionContracts, futuresOptionRowPl } from '../utils/positionPl'
import { getMultiplier, MULTIPLIER } from '../utils/contractMultiplier'
import {
  futuresMarginEstimate, ideaStress, ideaFit, worstCushion, rootLean, takeProfitCandidates,
  equityShort, expiringSoon, uncoveredShares, concentration, expiryCalendar,
  stressBook, cushionChange, marginCallMove,
} from '../utils/homeInsights'

/*
 * Home: what to trade today, new income first. Account data loads fresh on
 * every visit (never cached) and refreshes only on the Refresh button — no
 * polling, so an idle tab still signs out. Every section loads on its own,
 * so a slow one (the /ES and /NQ ideas) doesn't hold up the rest. The rules
 * (thresholds, idea filters, the futures margin estimate) are home.* in
 * config/app.properties; the logic is utils/homeInsights.js.
 */

const ROOTS = ['ES', 'NQ']
const DEFAULT_RULES = {
  'home.futures_margin_pct': 11, 'home.available_funds': 0, 'home.take_profit_pct': 75, 'home.expiring_days': 7, 'home.at_risk_pct': 2,
  'home.concentration_pct': 25, 'home.idea_max_dte': 7, 'home.idea_min_delta_pct': 5, 'home.idea_max_delta_pct': 20,
  'home.stress_iv_rise': 20, 'home.idea_crash_pct': 5,
}
const CALENDAR_DAYS = 14
const IDEAS_SHOWN = 8
const STRESS_MOVES = [-0.20, -0.10, -0.05, 0.05, 0.10]

const iso = (d) => d.toISOString().slice(0, 10)
const signClass = (v) => (v > 0 ? 'cell-positive' : v < 0 ? 'cell-negative' : '')
const pct = (v, digits = 1) => (v == null ? '—' : `${v.toFixed(digits)}%`)
const STATUS = {
  itm: { label: 'In the money', tone: 'error' },
  at_risk: { label: 'Near strike', tone: 'warning' },
  otm: { label: 'Out of the money', tone: 'ok' },
}

// A futures-option position row as a short for the rules (null for a long;
// a grouped ratio spread has no single strike, so no moneyness).
function futuresShort(row, type, bids, prices) {
  const quantity = row.quantity ?? null
  if (row.long_leg ? !(row.total_value > 0) : !(quantity < 0)) return null
  return {
    key: row.symbol,
    ticker: `/${row.ticker}`,
    type,
    strike: row.strike_price ?? null,
    expiration: row.expiration_date,
    dte: row.days_to_expiry,
    quantity,
    label: row.long_leg ? `/${row.ticker} ${row.ratio} ratio ${formatDate(row.expiration_date)}` : null,
    underlyingPrice: row.long_leg ? null : prices[row.ticker] ?? null,
    credit: row.total_value ?? 0,
    pl: futuresOptionRowPl(row, bids),
  }
}

const contractLabel = (s) => s.label ?? formatOptionSymbol(s.ticker, s.expiration, s.strike, s.type) ?? s.key

// Router-state handoff to Analyze, as Positions and the Screener use.
function analyzeState(legs) {
  return { state: { analyzePositions: legs, view: 'graph' } }
}

export default function Home() {
  const navigate = useNavigate()
  const [refreshKey, setRefreshKey] = useState(0)
  const [rules, setRules] = useState(DEFAULT_RULES)
  const [rulesLoaded, setRulesLoaded] = useState(false)
  const [book, setBook] = useState({ loading: true }) // positions + futures + quotes
  const [month, setMonth] = useState({ loading: true }) // month-to-date realized
  const [ideas, setIdeas] = useState({ loading: true })
  const [ideaSide, setIdeaSide] = useState('PUT')

  useEffect(() => {
    getAppConfig().then((c) => setRules((r) => ({ ...r, ...c }))).catch(() => {}).finally(() => setRulesLoaded(true))
  }, [])

  // Positions, futures and their live prices.
  useEffect(() => {
    let cancelled = false
    setBook({ loading: true })
    ;(async () => {
      try {
        const [positions, futures, futuresOptions] = await Promise.all([
          getPositions(),
          getFuturesPosition().catch(() => null),
          getFuturesOptionPosition().catch(() => null),
        ])
        const roots = [...new Set([...ROOTS, ...(futures ?? []).map((f) => f.symbol)])]
        // Equity options' deltas for the margin stress test (their P&L and
        // price come from Schwab already).
        const equityContracts = [['PUT', positions.puts ?? []], ['CALL', positions.calls ?? []]].flatMap(([type, rows]) =>
          rows.filter((r) => r.expiration_date).map((r) => ({
            key: r.symbol, underlying: r.ticker, expiration: r.expiration_date, strike: r.strike_price, type,
          })))
        const [prices, futuresQuotes, equityQuotes] = await Promise.all([
          getMarketQuotes({ futures: roots }).then((q) => q.futures ?? {}).catch(() => ({})),
          getOptionQuotes(futuresOptionContracts(futuresOptions?.puts, futuresOptions?.calls)).catch(() => ({})),
          getOptionQuotes(equityContracts).catch(() => ({})),
        ])
        const bids = {}
        for (const [key, q] of Object.entries(futuresQuotes)) if (q.bid != null) bids[key] = q.bid
        if (!cancelled) setBook({ loading: false, positions, futures, futuresOptions, prices, bids, futuresQuotes, equityQuotes })
      } catch (err) {
        if (!cancelled) setBook({ loading: false, error: friendlyErrorMessage(err, 'Could not load your positions.') })
      }
    })()
    return () => { cancelled = true }
  }, [refreshKey])

  // Month-to-date realized P&L: trades closed this month plus income and fees.
  useEffect(() => {
    let cancelled = false
    setMonth({ loading: true })
    const now = new Date()
    const start = iso(new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1)))
    const end = iso(now)
    Promise.all([
      getAllocations(start, end, true),
      getEquityTransactions('', start, end, 'ALL', true),
      getIncomeAndFees(start, end).catch(() => []),
    ])
      .then(([options, equity, cash]) => {
        if (cancelled) return
        const sum = (rows) => rows.reduce((s, r) => s + (r.total_amount ?? 0), 0)
        const optionsPl = sum(closedTrades(options ?? []))
        const equityPl = sum(closedTrades(equity ?? [], { dropZero: true }))
        const cashPl = (cash ?? []).reduce((s, r) => s + (r.amount ?? 0), 0)
        setMonth({ loading: false, total: optionsPl + equityPl + cashPl, options: optionsPl, equity: equityPl, cash: cashPl })
      })
      .catch((err) => !cancelled && setMonth({ loading: false, error: friendlyErrorMessage(err, 'Could not load this month.') }))
    return () => { cancelled = true }
  }, [refreshKey])

  // New-income ideas: /ES and /NQ short puts and calls under the idea rules
  // — once the rules have loaded, so the screener (the heaviest request)
  // runs once per visit, not again when they arrive.
  useEffect(() => {
    if (!rulesLoaded) return
    let cancelled = false
    setIdeas({ loading: true })
    const filters = {
      symbols: ROOTS.map((r) => `/${r}`),
      minDte: 0,
      maxDte: rules['home.idea_max_dte'],
      minMoneyness: 0,
      maxMoneyness: 10,
      minDelta: rules['home.idea_min_delta_pct'] / 100,
      maxDelta: rules['home.idea_max_delta_pct'] / 100,
    }
    Promise.all(['PUT', 'CALL'].map((strategy) => screenOptions({ ...filters, strategy })))
      .then(([puts, calls]) => {
        if (!cancelled) setIdeas({ loading: false, PUT: puts.results ?? [], CALL: calls.results ?? [], errors: [...(puts.errors ?? []), ...(calls.errors ?? [])] })
      })
      .catch((err) => !cancelled && setIdeas({ loading: false, error: friendlyErrorMessage(err, 'Could not load /ES and /NQ ideas.') }))
    return () => { cancelled = true }
  }, [refreshKey, rules, rulesLoaded])

  const derived = useMemo(() => {
    if (book.loading || book.error) return null
    const { positions, futures, futuresOptions, prices, bids, futuresQuotes, equityQuotes } = book
    const puts = positions.puts ?? []
    const calls = positions.calls ?? []
    const stocks = positions.stocks ?? []
    const balances = positions.balances ?? {}
    const shorts = [
      ...puts.map((r) => equityShort(r, 'PUT')),
      ...calls.map((r) => equityShort(r, 'CALL')),
      ...(futuresOptions?.puts ?? []).map((r) => futuresShort(r, 'PUT', bids, prices)),
      ...(futuresOptions?.calls ?? []).map((r) => futuresShort(r, 'CALL', bids, prices)),
    ].filter(Boolean)
    const futMargin = futuresMarginEstimate(futures ?? [], prices, rules['home.futures_margin_pct'])
    const maint = balances.maintenance_requirement ?? 0
    const netLiq = balances.account_value ?? null

    // The book for the margin stress test (utils/homeInsights.js revalues
    // it after each move). Equity options price from Schwab's mark, with
    // implied volatility and delta from Tastytrade.
    const stressPositions = []
    for (const s of stocks) {
      stressPositions.push({ kind: 'stock', qty: s.quantity, price: s.current_price ?? null, req: s.maintenance_requirement ?? 0 })
    }
    for (const [type, rows] of [['PUT', puts], ['CALL', calls]]) {
      for (const r of rows) {
        const q = equityQuotes?.[r.symbol] ?? {}
        stressPositions.push({
          kind: 'option', root: null, type, strike: r.strike_price, dte: r.days_to_expiry, qty: r.quantity, mult: MULTIPLIER,
          spot: r.underlying_price ?? null, iv: q.iv ?? null, mid: r.current_price ?? q.mid ?? null, delta: q.delta ?? null,
          req: r.maintenance_requirement ?? 0,
        })
      }
    }
    for (const f of futures ?? []) {
      stressPositions.push({ kind: 'future', root: f.symbol, qty: f.quantity, price: prices[f.symbol] ?? null, mult: getMultiplier(f.symbol) })
    }
    for (const [type, rows] of [['PUT', futuresOptions?.puts ?? []], ['CALL', futuresOptions?.calls ?? []]]) {
      for (const r of rows) {
        const legs = r.long_leg
          ? [[r.long_leg, r.long_leg.amount], [r.short_leg, -r.short_leg.amount]]
          : [[r, r.quantity]]
        for (const [leg, qty] of legs) {
          const q = futuresQuotes?.[leg.symbol] ?? {}
          stressPositions.push({
            kind: 'option', root: r.ticker, type, strike: leg.strike_price, dte: r.days_to_expiry, qty,
            mult: r.multiplier ?? getMultiplier(r.ticker), spot: prices[r.ticker] ?? null,
            iv: q.iv ?? null, mid: q.mid ?? null, delta: q.delta ?? null,
          })
        }
      }
    }
    const stress = stressBook(stressPositions)
    const stressOptions = { futuresPct: rules['home.futures_margin_pct'], ivRise: rules['home.stress_iv_rise'] }
    // Available funds: thinkorswim's figure from app.properties when set
    // (futures included), else Schwab's (securities only).
    const fundsFromSettings = rules['home.available_funds'] > 0
    const cushion = fundsFromSettings ? rules['home.available_funds'] : balances.available_funds ?? null
    return {
      balances,
      netLiq,
      prices,
      futuresMissing: futures == null || futuresOptions == null,
      futMargin,
      marginUsed: maint + futMargin.total,
      shorts,
      expiring: expiringSoon(shorts, rules['home.expiring_days'], rules['home.at_risk_pct']),
      takeProfit: takeProfitCandidates(shorts, rules['home.take_profit_pct']),
      uncovered: uncoveredShares(stocks, puts, calls),
      concentrated: concentration(stocks, puts, netLiq, rules['home.concentration_pct']),
      calendar: expiryCalendar(shorts, CALENDAR_DAYS),
      cushion,
      fundsFromSettings,
      unpricedRisk: stress.unpriced,
      stress: cushion == null ? [] : STRESS_MOVES.map((move) => ({ move, after: cushion + cushionChange(stress, move, stressOptions).change })),
      // For the new-income ideas, judged against this book.
      stressBook: stress,
      stressOptions,
      lean: rootLean(stress.positions),
      callDrop: cushion == null ? null : marginCallMove(cushion, stress, -1, stressOptions),
      callRally: cushion == null ? null : marginCallMove(cushion, stress, 1, stressOptions),
    }
  }, [book, rules])

  const marginPct = rules['home.futures_margin_pct']
  const funds = derived?.cushion ?? null
  const crashPct = rules['home.idea_crash_pct']
  const ideaOptions = derived && { ...derived.stressOptions, crashPct }
  // The book's worst cushion after a crashPct move either way, before any
  // new trade.
  const worstNow = useMemo(
    () => (derived?.cushion == null ? null : worstCushion(derived.cushion, derived.stressBook, [], ideaOptions)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [derived, crashPct],
  )
  // The best strike per root and expiration — neighbouring strikes of one
  // expiry would otherwise fill the list — then the best of those first.
  // Each idea is judged against the current book (its /ES and /NQ
  // positions above all): how much one contract lowers the worst cushion
  // after a crashPct move either way. One that offsets what the book holds
  // is a hedge and ranks first; one that stacks on it ranks by credit over
  // the risk it adds — not annualized, which makes a 1-day put look best
  // though a crash costs it the most premiums' worth.
  const ideaRows = useMemo(() => {
    const fitted = (r, maxQty) => (worstNow == null ? {} : ideaFit(derived.cushion, derived.stressBook, r, ideaOptions, { maxQty, base: worstNow }))
    const rank = (a, b) => (b.hedges - a.hedges) || (a.hedges ? b.credit - a.credit : (b.returnOnRisk ?? 0) - (a.returnOnRisk ?? 0))
    const best = {}
    for (const r of ideas[ideaSide] ?? []) {
      const stressed = ideaStress(r, { crashPct, futuresPct: marginPct, ivRise: rules['home.stress_iv_rise'] })
      if (!stressed) continue
      const row = { ...r, ...stressed }
      Object.assign(row, fitted(row, 0))
      const key = `${r.underlying}|${r.expirationDate}`
      if (!best[key] || rank(row, best[key]) < 0) best[key] = row
    }
    return Object.values(best)
      .sort(rank)
      .slice(0, IDEAS_SHOWN)
      .map((row) => ({ ...row, maxContracts: worstNow == null ? null : fitted(row, 100).maxContracts }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideas, ideaSide, marginPct, crashPct, worstNow, rules])

  const calendarCredit = (derived?.calendar ?? []).reduce((s, d) => s + d.credit, 0)

  return (
    <div className="page home">
      <div className="home-head">
        <h2 className="home-title">Today</h2>
        <button type="button" className="btn btn-secondary" onClick={() => setRefreshKey((k) => k + 1)}>Refresh</button>
      </div>

      {book.error && <div className="alert error">{book.error}</div>}

      {/* 1. Capacity and results */}
      <div className="card">
        <div className="metrics-row home-metrics">
          <Metric
            label="Securities net liq"
            value={derived ? money(derived.netLiq) : '…'}
            title="Schwab's net liquidation value for the securities account only — the futures account isn't in Schwab's API, so thinkorswim's Net Liq is higher."
          />
          <Metric
            label="Securities available funds"
            title="Schwab's available funds for the securities account only — thinkorswim's Available Funds For Trading is lower, since it also sets aside futures margin the futures account doesn't cover."
            value={derived ? money(funds) : '…'}
            sub={derived?.balances.buying_power != null ? `${money(derived.balances.buying_power)} buying power` : null}
          />
          <Metric
            label="Margin used"
            value={derived ? money(derived.marginUsed) : '…'}
            sub={derived && derived.netLiq
              ? `${pct((derived.marginUsed / derived.netLiq) * 100)} of securities net liq · futures est. ${money(derived.futMargin.total)} (${marginPct}%)`
              : null}
            title={`Schwab's maintenance requirement for stocks and options, plus futures margin estimated at ${marginPct}% of the futures' notional (home.futures_margin_pct in app.properties — Schwab doesn't report futures margin).`}
          />
          <Metric
            label="This month"
            value={month.loading ? '…' : month.error ? '—' : <span className={signClass(month.total)}>{money(month.total)}</span>}
            sub={month.loading || month.error ? month.error : `Options ${money(month.options)} · Equity & futures ${money(month.equity)} · Income & fees ${money(month.cash)}`}
          />
          <Metric
            label="Premium expiring"
            value={derived ? money(calendarCredit) : '…'}
            sub={derived ? `next ${CALENDAR_DAYS} days · ${count(derived.calendar.reduce((s, d) => s + d.count, 0))} positions` : null}
          />
        </div>
      </div>

      {/* Margin cushion: how much can be lost before a margin call */}
      <div className="card">
        <div className="home-card-head">
          <h3 className="section-title">Margin cushion</h3>
          <span className="summary-line">Loss the account can take before a margin call</span>
        </div>
        {book.loading ? <Spinner /> : derived && derived.cushion != null ? (
          <>
            <div className="home-cushion">
              <div className="home-cushion-now">
                <span className="metric-label">{derived.fundsFromSettings ? 'Now (from thinkorswim)' : 'Now (securities only)'}</span>
                <span className={`home-cushion-value ${derived.cushion < 0 ? 'cell-negative' : ''}`}>{money(derived.cushion)}</span>
                <span className="summary-line">
                  Margin call at {derived.callDrop == null ? 'no drop up to 60%' : `about a ${pct(-derived.callDrop * 100, 1)} drop`}
                  {' · '}{derived.callRally == null ? 'no rally up to 60%' : `about a ${pct(derived.callRally * 100, 1)} rally`}
                </span>
              </div>
              <div className="home-stress">
                <table className="data-table">
                  <thead>
                    <tr><th>Market move</th>{derived.stress.map((s) => <th key={s.move} className="num">{s.move > 0 ? '+' : ''}{(s.move * 100).toFixed(0)}%</th>)}</tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Cushion after</td>
                      {derived.stress.map((s) => (
                        <td key={s.move} className={`num ${s.after < 0 ? 'cell-negative' : ''}`}>{money(s.after, 0)}</td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            {derived.unpricedRisk > 0 && (
              <p className="summary-line">
                {derived.unpricedRisk} position{derived.unpricedRisk === 1 ? '' : 's'} with no price {derived.unpricedRisk === 1 ? 'is' : 'are'} left out of the stress test.
              </p>
            )}
          </>
        ) : <p className="summary-line">Schwab didn't return available funds.</p>}
      </div>

      {/* 2. New income: /ES and /NQ */}
      <div className="card">
        <div className="home-card-head">
          <h3 className="section-title">New income · /ES &amp; /NQ</h3>
          <div className="tab-row home-side-tabs" role="tablist" aria-label="Puts or calls">
            {['PUT', 'CALL'].map((side) => (
              <button key={side} type="button" role="tab" aria-selected={ideaSide === side}
                className={`tab-item ${ideaSide === side ? 'active' : ''}`} onClick={() => setIdeaSide(side)}>
                {side === 'PUT' ? 'Short puts' : 'Short calls'}
              </button>
            ))}
          </div>
        </div>
        <div className="home-roots">
          {ROOTS.map((root) => {
            const price = derived?.prices[root]
            const lean = derived?.lean[root] ?? 0
            return (
              <div key={root} className="home-root">
                <span className="home-root-name">/{root}</span>
                <span className="home-root-price">{price == null ? '—' : price.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
                {derived && (
                  <span className="summary-line">
                    {Math.abs(lean) < 0.05 ? 'book flat' : `book net ${lean > 0 ? 'long' : 'short'} ${Math.abs(lean).toFixed(1)} /${root}`}
                  </span>
                )}
              </div>
            )
          })}
        </div>
        <p className="summary-line">
          Expiring within {rules['home.idea_max_dte']} days, delta {(rules['home.idea_min_delta_pct'] / 100).toFixed(2)}–{(rules['home.idea_max_delta_pct'] / 100).toFixed(2)},
          judged against your positions as if the market moves {crashPct}% either way at once — trades that offset them first.
          {worstNow != null && (worstNow > 0
            ? ` Worst cushion after that move today: ${money(worstNow, 0)}.`
            : ` That move would already leave no cushion (${money(worstNow, 0)}) — only trades that offset your risk fit.`)}
        </p>
        {ideas.loading && <Spinner />}
        {ideas.error && <div className="alert error">{ideas.error}</div>}
        {!ideas.loading && !ideas.error && (
          ideaRows.length ? (
            <DataTable
              data={ideaRows}
              paginate={false}
              columns={[
                { key: 'symbol', label: 'Contract', render: (r) => formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type) ?? r.symbol },
                { key: 'dte', label: 'DTE', align: 'right' },
                { key: 'otmPct', label: 'OTM', align: 'right', render: (r) => pct(r.otmPct) },
                { key: 'delta', label: 'Delta', align: 'right', render: (r) => (r.delta == null ? '—' : Math.abs(r.delta).toFixed(2)) },
                { key: 'credit', label: 'Credit', align: 'right', render: (r) => money(r.credit) },
                {
                  key: 'crashLoss', label: `Loss at ${ideaSide === 'PUT' ? '−' : '+'}${crashPct}%`, align: 'right',
                  render: (r) => <span className={r.crashLoss > 0 ? 'cell-negative' : ''}>{money(Math.max(0, r.crashLoss), 0)}</span>,
                },
                {
                  key: 'riskAdded', label: 'Risk to book', align: 'right',
                  render: (r) => (r.riskAdded == null ? '—' : r.hedges
                    ? <span className="home-chip home-chip--ok">Offsets</span>
                    : money(r.riskAdded, 0)),
                },
                { key: 'returnOnRisk', label: 'Return on risk', align: 'right', render: (r) => (r.hedges ? '—' : pct(r.returnOnRisk, 2)) },
                { key: 'maxContracts', label: 'Max qty', align: 'right', render: (r) => (r.maxContracts == null ? '—' : count(r.maxContracts)) },
                {
                  key: 'analyze', label: '',
                  render: (r) => (
                    <button type="button" className="btn btn-secondary home-row-btn" onClick={() => navigate('/analyze', analyzeState([{
                      symbol: r.underlying, ticker: r.underlying, dte: r.dte, expirationDate: r.expirationDate,
                      strike: r.strike, optionType: r.type, quantity: -1, premium: r.bid,
                    }]))}>Analyze</button>
                  ),
                },
              ]}
            />
          ) : <p className="summary-line">No /ES or /NQ {ideaSide === 'PUT' ? 'puts' : 'calls'} match the rules right now.</p>
        )}
      </div>

      {/* 3. Income from what you hold, and capital to free up */}
      <div className="home-grid">
        <div className="card">
          <h3 className="section-title">Shares to sell against</h3>
          <p className="summary-line">Shares not yet covered by a short call (long) or short put (short).</p>
          {book.loading ? <Spinner /> : derived?.uncovered.length ? (
            <ul className="home-list">
              {derived.uncovered.map((u) => (
                <li key={u.ticker}>
                  <span className="home-list-main">{u.ticker}</span>
                  <span>Sell up to {u.contracts} covered {u.side === 'CALL' ? 'call' : 'put'}{u.contracts === 1 ? '' : 's'}</span>
                  <span className="summary-line">{count(u.shares)} shares{u.price != null ? ` at ${money(u.price)}` : ''}</span>
                </li>
              ))}
            </ul>
          ) : <p className="summary-line">Every share is covered.</p>}
        </div>

        <div className="card">
          <h3 className="section-title">Take profit</h3>
          <p className="summary-line">Shorts that have kept {rules['home.take_profit_pct']}% or more of their premium: close and redeploy.</p>
          {book.loading ? <Spinner /> : derived?.takeProfit.length ? (
            <ul className="home-list">
              {derived.takeProfit.map((s) => (
                <li key={s.key}>
                  <span className="home-list-main">{contractLabel(s)}</span>
                  <span className="cell-positive">{pct(s.kept, 0)} kept</span>
                  <span className="summary-line">{money(s.pl)} of {money(s.credit)} · {s.dte} DTE</span>
                </li>
              ))}
            </ul>
          ) : <p className="summary-line">Nothing at the threshold yet.</p>}
        </div>
      </div>

      {/* 4. Risk: what expires soon, and where the account is concentrated */}
      <div className="card">
        <h3 className="section-title">Expiring within {rules['home.expiring_days']} days</h3>
        {book.loading ? <Spinner /> : derived?.expiring.length ? (
          <DataTable
            data={derived.expiring}
            paginate={false}
            columns={[
              { key: 'key', label: 'Contract', render: contractLabel },
              { key: 'dte', label: 'DTE', align: 'right' },
              {
                key: 'status', label: 'Status',
                render: (s) => (s.status ? <span className={`home-chip home-chip--${STATUS[s.status].tone}`}>{STATUS[s.status].label}</span> : '—'),
              },
              { key: 'distance', label: 'Cushion', align: 'right', render: (s) => (s.distance == null ? '—' : pct(s.distance)) },
              { key: 'underlyingPrice', label: 'Underlying', align: 'right', render: (s) => money(s.underlyingPrice) },
              { key: 'pl', label: 'P&L', align: 'right', render: (s) => <span className={signClass(s.pl)}>{money(s.pl)}</span> },
            ]}
          />
        ) : <p className="summary-line">No short options expire in that window.</p>}
        {derived?.futuresMissing && <p className="summary-line">Futures options couldn't be loaded, so they're left out.</p>}
      </div>

      <div className="home-grid">
        <div className="card">
          <h3 className="section-title">Expiry calendar · next {CALENDAR_DAYS} days</h3>
          {book.loading ? <Spinner /> : derived?.calendar.length ? (
            <div className="home-calendar">
              {derived.calendar.map((d) => (
                <div key={d.date} className="home-day">
                  <span className="home-day-date">{formatDate(d.date).slice(0, 5)}</span>
                  <span className="home-day-count">{d.count} short{d.count === 1 ? '' : 's'}</span>
                  <span className="home-day-credit">{money(d.credit, 0)}</span>
                </div>
              ))}
            </div>
          ) : <p className="summary-line">Nothing expires in the next {CALENDAR_DAYS} days.</p>}
        </div>

        <div className="card">
          <h3 className="section-title">Concentration</h3>
          <p className="summary-line">Tickers above {rules['home.concentration_pct']}% of securities net liq (shares plus short puts' strike value).</p>
          {book.loading ? <Spinner /> : derived?.concentrated.length ? (
            <ul className="home-list">
              {derived.concentrated.map((c) => (
                <li key={c.ticker}>
                  <span className="home-list-main">{c.ticker}</span>
                  <span>{pct(c.share, 0)} of securities net liq</span>
                  <span className="summary-line">{money(c.exposure, 0)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="summary-line">No ticker above the limit.</p>}
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, sub, title }) {
  return (
    <div className="metric" title={title}>
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {sub && <span className="metric-subtext summary-line">{sub}</span>}
    </div>
  )
}
