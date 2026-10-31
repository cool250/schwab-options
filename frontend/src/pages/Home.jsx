import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getAppConfig, getPositions, getFuturesPosition, getFuturesOptionPosition, getMarketQuotes, getOptionQuotes,
  getAllocations, getEquityTransactions, getIncomeAndFees, screenOptions, getMarketEvents, getWatchlist, friendlyErrorMessage,
} from '../api/client'
import HelpTip from '../components/HelpTip'
import DataTable from '../components/DataTable'
import { money, count } from '../utils/numberFormat'
import { formatDate } from '../utils/dateFormat'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { closedTrades } from '../utils/reportStats'
import { futuresOptionContracts, futuresOptionRowPl } from '../utils/positionPl'
import { getMultiplier, MULTIPLIER } from '../utils/contractMultiplier'
import {
  ideaStress, ideaFit, worstCushion, rootLean, callsCoverLeft, takeProfitCandidates,
  equityShort, eventsBefore, expiringSoon, uncoveredShares, expiryCalendar,
  stressBook, marginCallMove, cushionStatus, availableFundsForTrading,
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
// On a phone (DataTable's cards): the contract and its key number on top.
// The watchlist, events and calendar are short enough to stay tables.
const IDEA_CARDS = { title: ['symbol', 'returnOnRisk'], fields: ['credit', 'riskAdded', 'maxContracts', 'analyze'] }
const EXPIRING_CARDS = { title: ['key', 'pl'], fields: ['dte', 'status', 'distance', 'underlyingPrice', 'events'] }
const TAKE_PROFIT_CARDS = { title: ['key', 'pl'], fields: ['kept', 'credit'] }
const DEFAULT_RULES = {
  'home.futures_margin_pct': 11, 'home.take_profit_pct': 75, 'home.expiring_days': 7, 'home.at_risk_pct': 2,
  'home.idea_max_dte': 7, 'home.idea_min_delta_pct': 5, 'home.idea_max_delta_pct': 20,
  'home.stress_iv_rise': 20, 'home.idea_crash_pct': 5, 'home.event_crash_pct': 8,
}
const CALENDAR_DAYS = 14
const IDEAS_SHOWN = 8
const EVENTS_DAYS = 14

const iso = (d) => d.toISOString().slice(0, 10)
const signClass = (v) => (v > 0 ? 'cell-positive' : v < 0 ? 'cell-negative' : '')
const pct = (v, digits = 1) => (v == null ? '—' : `${v.toFixed(digits)}%`)
const CUSHION_STATUS = {
  healthy: { label: 'Healthy', tone: 'ok' },
  watch: { label: 'Watch', tone: 'warning' },
  at_risk: { label: 'At risk', tone: 'error' },
}
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

// "Wed 10/28" and "8:30 AM" for an event's ET date and time.
const eventDay = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric', timeZone: 'UTC' })
function eventTime(t) {
  const [h, m] = t.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}
// Short names for a position's upcoming events, major ones as warnings.
const EVENT_SHORT = { FOMC: 'FOMC', EARNINGS: 'Earnings', EX_DIVIDEND: 'Ex-div' }
function EventChips({ events }) {
  if (!events?.length) return '—'
  return (
    <span className="home-event-chips">
      {events.map((e) => (
        <span key={`${e.date}|${e.name}`} className={`home-chip home-chip--${e.major ? 'warning' : 'ok'}`} title={`${e.name} · ${eventDay(e.date)}`}>
          {EVENT_SHORT[e.kind] ?? e.name} {e.date.slice(5).replace('-', '/')}
        </span>
      ))}
    </span>
  )
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
  const [events, setEvents] = useState({ loading: true }) // upcoming releases, FOMC, earnings
  const [watch, setWatch] = useState({ loading: true }) // prices for the positions' tickers

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
        if (!cancelled) setBook({ loading: false, loadedAt: new Date(), positions, futures, futuresOptions, prices, bids, futuresQuotes, equityQuotes })
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

  // Upcoming events — once positions are in, for their tickers' earnings
  // and ex-dividend dates.
  useEffect(() => {
    if (book.loading) return
    let cancelled = false
    const p = book.positions ?? {}
    const symbols = [...new Set([
      ...(p.stocks ?? []).map((s) => s.symbol),
      ...[...(p.puts ?? []), ...(p.calls ?? [])].map((r) => r.ticker),
    ].filter(Boolean))].slice(0, 100)
    const days = Math.max(EVENTS_DAYS, rules['home.idea_max_dte'], rules['home.expiring_days']) + 1
    setEvents({ loading: true })
    getMarketEvents(symbols, days)
      .then((r) => !cancelled && setEvents({ loading: false, list: r.events ?? [], notes: r.notes ?? [] }))
      .catch(() => !cancelled && setEvents({ loading: false, list: [], notes: ['Events are unavailable right now.'] }))
    return () => { cancelled = true }
  }, [book, rules])

  // Watchlist: /ES and /NQ, then every ticker held (shares or options),
  // alphabetical — loaded once positions are in.
  useEffect(() => {
    if (book.loading) return
    let cancelled = false
    const p = book.positions ?? {}
    const held = [...new Set([
      ...(p.stocks ?? []).map((s) => s.symbol),
      ...[...(p.puts ?? []), ...(p.calls ?? [])].map((r) => r.ticker),
    ].filter(Boolean))].sort()
    const symbols = [...ROOTS.map((r) => `/${r}`), ...held].slice(0, 60)
    setWatch({ loading: true })
    getWatchlist(symbols)
      .then((rows) => !cancelled && setWatch({ loading: false, rows: rows ?? [] }))
      .catch(() => !cancelled && setWatch({ loading: false, rows: [], error: true }))
    return () => { cancelled = true }
  }, [book])

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
    // Available funds for trading, futures included — computed from Schwab's
    // balances and an estimated futures margin; Schwab's own (securities
    // only) when the futures book couldn't be loaded.
    const forTrading = futures == null || futuresOptions == null ? null : availableFundsForTrading(balances, stress, stressOptions)
    const cushion = forTrading?.funds ?? balances.available_funds ?? null
    const callDrop = cushion == null ? null : marginCallMove(cushion, stress, -1, stressOptions)
    return {
      balances,
      prices,
      futuresMissing: futures == null || futuresOptions == null,
      shorts,
      expiring: expiringSoon(shorts, rules['home.expiring_days'], rules['home.at_risk_pct']),
      takeProfit: takeProfitCandidates(shorts, rules['home.take_profit_pct']),
      uncovered: uncoveredShares(stocks, puts, calls),
      calendar: expiryCalendar(shorts, CALENDAR_DAYS),
      forTrading,
      cushion,
      // For the new-income ideas, judged against this book.
      stressBook: stress,
      stressOptions,
      lean: rootLean(stress.positions),
      coverLeft: callsCoverLeft(stress.positions),
      // For the alert line: the market moves that would bring a margin call.
      callDrop,
      callRally: cushion == null ? null : marginCallMove(cushion, stress, 1, stressOptions),
    }
  }, [book, rules])

  const marginPct = rules['home.futures_margin_pct']
  const crashPct = rules['home.idea_crash_pct']
  const ideaOptions = derived && { ...derived.stressOptions, crashPct }
  // An idea that lives through a major event (CPI, jobs, PCE, FOMC) is
  // judged against the larger home.event_crash_pct move.
  const eventCrashPct = Math.max(crashPct, rules['home.event_crash_pct'])
  const eventOptions = derived && { ...derived.stressOptions, crashPct: eventCrashPct }
  const eventList = events.list ?? []
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
  const worstEvent = useMemo(
    () => (derived?.cushion == null ? null : worstCushion(derived.cushion, derived.stressBook, [], eventOptions)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [derived, eventCrashPct],
  )
  const ideaRows = useMemo(() => {
    const fitted = (r, maxQty) => (worstNow == null ? {} : r.eventCrash
      ? ideaFit(derived.cushion, derived.stressBook, r, eventOptions, { maxQty, base: worstEvent })
      : ideaFit(derived.cushion, derived.stressBook, r, ideaOptions, { maxQty, base: worstNow }))
    const rank = (a, b) => (b.hedges - a.hedges) || (a.hedges ? b.credit - a.credit : (b.returnOnRisk ?? 0) - (a.returnOnRisk ?? 0))
    const best = {}
    for (const r of ideas[ideaSide] ?? []) {
      const crossed = eventsBefore(eventList, { ticker: r.underlying, type: r.type, expiration: r.expirationDate })
      const eventCrash = crossed.some((e) => e.major)
      const stressed = ideaStress(r, { crashPct: eventCrash ? eventCrashPct : crashPct, futuresPct: marginPct, ivRise: rules['home.stress_iv_rise'] })
      if (!stressed) continue
      const row = { ...r, ...stressed, events: crossed, eventCrash }
      Object.assign(row, fitted(row, 0))
      const key = `${r.underlying}|${r.expirationDate}`
      if (!best[key] || rank(row, best[key]) < 0) best[key] = row
    }
    return Object.values(best)
      .sort(rank)
      .slice(0, IDEAS_SHOWN)
      .map((row) => {
        if (worstNow == null) return { ...row, maxContracts: null }
        const byCushion = fitted(row, 100).maxContracts
        // New short calls stay covered: no more than the long futures not
        // yet sold against.
        const cover = row.type === 'CALL' ? derived.coverLeft[row.underlying.replace(/^\//, '')] ?? 0 : null
        return { ...row, maxContracts: cover == null ? byCushion : Math.min(byCushion, cover), capped: cover != null && cover < byCushion }
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideas, ideaSide, marginPct, crashPct, worstNow, worstEvent, eventCrashPct, eventList, rules])

  const calendarCredit = (derived?.calendar ?? []).reduce((s, d) => s + d.credit, 0)
  const cushionState = derived?.cushion == null ? null : cushionStatus(derived.callDrop, derived.callRally)
  const eventsShown = eventList
    .filter((e) => e.date <= iso(new Date(Date.now() + EVENTS_DAYS * 86400000)))
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time ?? '99:99').localeCompare(b.time ?? '99:99'))

  // The alert line: what needs attention today, each linking to its card.
  const alerts = []
  if (derived) {
    if (cushionState && cushionState.status !== 'healthy') {
      alerts.push({
        tone: CUSHION_STATUS[cushionState.status].tone,
        text: `Margin call at a ${pct(cushionState.nearest * 100, 1)} move · cushion ${money(derived.cushion, 0)}`,
      })
    }
    const itm = derived.expiring.filter((s) => s.status === 'itm').length
    const near = derived.expiring.filter((s) => s.status === 'at_risk').length
    if (itm) alerts.push({ tone: 'error', href: '#home-expiring', text: `${itm} expiring short${itm === 1 ? '' : 's'} in the money` })
    if (near) alerts.push({ tone: 'warning', href: '#home-expiring', text: `${near} near the strike` })
    if (derived.takeProfit.length) {
      alerts.push({ tone: 'ok', href: '#home-take-profit', text: `${derived.takeProfit.length} short${derived.takeProfit.length === 1 ? '' : 's'} to take profit on` })
    }
  }
  const soon = iso(new Date(Date.now() + 3 * 86400000))
  for (const e of eventsShown.filter((e) => e.major && e.date <= soon)) {
    alerts.push({ tone: 'warning', href: '#home-events', text: `${e.name} ${eventDay(e.date)}${e.time ? ` ${eventTime(e.time)}` : ''}` })
  }

  const ideaCols = [
    {
      key: 'symbol', label: 'Contract',
      render: (r) => (
        <span className="home-contract" title={ideaDetail(r, crashPct, eventCrashPct)}>
          <span className="home-contract-name">{formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type) ?? r.symbol}</span>
          <span className="home-contract-meta">
            {r.dte} DTE · {pct(r.otmPct)} OTM{r.delta != null ? ` · Δ ${Math.abs(r.delta).toFixed(2)}` : ''}
            {r.events?.length > 0 && <> <EventChips events={r.events} /></>}
          </span>
        </span>
      ),
    },
    { key: 'credit', label: 'Credit', align: 'right', render: (r) => money(r.credit, 0) },
    {
      key: 'riskAdded', label: 'Risk to book', align: 'right',
      render: (r) => (r.riskAdded == null ? '—' : r.hedges
        ? <span className="home-chip home-chip--ok">Offsets</span>
        : money(r.riskAdded, 0)),
    },
    { key: 'returnOnRisk', label: 'Return on risk', align: 'right', render: (r) => (r.hedges ? '—' : pct(r.returnOnRisk, 2)) },
    {
      key: 'maxContracts', label: 'Max qty', align: 'right',
      render: (r) => (r.maxContracts == null ? '—' : r.capped
        ? <span title="Capped at the long futures not yet covered by a short call">{count(r.maxContracts)} · covered</span>
        : count(r.maxContracts)),
    },
    {
      key: 'analyze', label: '',
      render: (r) => (
        <button type="button" className="btn btn-secondary home-row-btn" onClick={() => navigate('/analyze', analyzeState([{
          symbol: r.underlying, ticker: r.underlying, dte: r.dte, expirationDate: r.expirationDate,
          strike: r.strike, optionType: r.type, quantity: -1, premium: r.bid,
        }]))}>Analyze</button>
      ),
    },
  ]

  const sharesEmpty = !book.loading && !derived?.uncovered.length
  const profitEmpty = !book.loading && !derived?.takeProfit.length

  return (
    <div className="page home">
      <div className="home-head">
        {book.loadedAt && <span className="summary-line home-updated">Updated {book.loadedAt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</span>}
        <button type="button" className="btn btn-secondary" onClick={() => setRefreshKey((k) => k + 1)}>Refresh</button>
      </div>

      {book.error && <div className="alert error">{book.error}</div>}

      {/* What needs attention today */}
      {!book.loading && !book.error && (
        <nav className="home-alerts" aria-label="Needs attention">
          {alerts.length
            ? alerts.map((a) => (a.href
              ? <a key={a.text} href={a.href} className={`home-alert home-chip--${a.tone}`}>{a.text}</a>
              : <span key={a.text} className={`home-alert home-chip--${a.tone}`}>{a.text}</span>))
            : <span className="summary-line">Nothing needs attention today.</span>}
        </nav>
      )}

      {/* 1. Capacity and results */}
      <div className="card" id="home-summary">
        <div className="metrics-row home-metrics">
          <Metric
            label="Cash and Sweep"
            value={derived ? money(derived.balances.cash_and_sweep, 0) : '…'}
            title="Schwab's cash balance plus the proceeds held for short stock — thinkorswim's Cash & Sweep Vehicle, for the securities account only."
          />
          <Metric
            label="Net Liquidity"
            title="Schwab's liquidation value across the securities and futures accounts — thinkorswim's Net Liq."
            value={derived ? money(derived.balances.net_liquidity, 0) : '…'}
          />
          <Metric
            label="Available funds for trading"
            value={derived ? money(derived.forTrading?.funds, 0) : '…'}
            sub={derived?.forTrading ? `est. futures margin ${money(derived.forTrading.futuresMargin, 0)}` : derived?.futuresMissing ? 'futures unavailable' : null}
            title={`Schwab's available funds for the securities account, plus the futures account's net liq, less futures margin — estimated as each root's worst loss over a ±${marginPct}% move (home.futures_margin_pct), since Schwab doesn't report it. Within a few percent of thinkorswim's Regular Futures Margin on a book of short futures options.`}
          />
          <Metric
            label="This month"
            value={month.loading ? '…' : month.error ? '—' : <span className={signClass(month.total)}>{money(month.total, 0)}</span>}
            sub={month.loading || month.error ? month.error : `Options ${money(month.options, 0)} · Equity & futures ${money(month.equity, 0)} · Income & fees ${money(month.cash, 0)}`}
          />
          <Metric
            label="Premium expiring"
            value={derived ? money(calendarCredit, 0) : '…'}
            sub={derived ? `next ${CALENDAR_DAYS} days · ${count(derived.calendar.reduce((s, d) => s + d.count, 0))} positions` : null}
          />
        </div>
      </div>

      {/* 2. New income, with the watchlist and upcoming events beside it */}
      <div className="home-grid home-grid--wide">
        <div className="card" id="home-ideas">
          <CardHead
            title="New income · /ES & /NQ"
            sub={`Ranked by return on risk to your book${worstNow != null ? ` · worst cushion after a ±${crashPct}% / ±${2 * crashPct}% move: ${money(worstNow, 0)}` : ''}`}
            help={<>
              Short options expiring within {rules['home.idea_max_dte']} days, delta {(rules['home.idea_min_delta_pct'] / 100).toFixed(2)}–{(rules['home.idea_max_delta_pct'] / 100).toFixed(2)},
              best strike per expiration. Each is judged against your positions as if the market moves {crashPct}% or {2 * crashPct}% either
              way at once ({eventCrashPct}% or {2 * eventCrashPct}% if it lives through CPI, jobs, PCE or an FOMC decision): Risk to book is
              how much one contract lowers the worst cushion, and Max qty the most that keep it above zero. Trades that offset your positions
              rank first; new calls are capped at the long futures not yet covered. Hover a contract for its own stress numbers.
            </>}
            right={(
              <div className="tab-row home-side-tabs" role="tablist" aria-label="Puts or calls">
                {['PUT', 'CALL'].map((side) => (
                  <button key={side} type="button" role="tab" aria-selected={ideaSide === side}
                    className={`tab-item ${ideaSide === side ? 'active' : ''}`} onClick={() => setIdeaSide(side)}>
                    {side === 'PUT' ? 'Short puts' : 'Short calls'}
                  </button>
                ))}
              </div>
            )}
          />
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
                      {ideaSide === 'CALL' && ` · ${derived.coverLeft[root] ?? 0} uncovered for calls`}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {worstNow != null && worstNow <= 0 && (
            <p className="summary-line">Those moves would already leave no cushion — only trades that offset your risk fit.</p>
          )}
          {ideas.loading && <Placeholder rows={5} />}
          {ideas.error && <div className="alert error">{ideas.error}</div>}
          {!ideas.loading && !ideas.error && (
            ideaRows.length
              ? <DataTable data={ideaRows} paginate={false} columns={ideaCols} cards={IDEA_CARDS} />
              : <p className="summary-line">No /ES or /NQ {ideaSide === 'PUT' ? 'puts' : 'calls'} match the rules right now.</p>
          )}
        </div>

        {/* The watchlist with upcoming events below it. */}
        <div className="home-stack">
          <div className="card" id="home-watchlist">
            <CardHead title="Watchlist" sub="/ES, /NQ and the tickers you hold" />
            {watch.loading ? <Placeholder rows={6} /> : watch.rows.length ? (
              <div className="home-compact-table">
                <DataTable
                  data={watch.rows}
                  paginate={false}
                  cards={false}
                  columns={[
                    {
                      key: 'symbol', label: 'Symbol',
                      render: (w) => (
                        <span className="home-contract-name" title={w.day_low != null && w.day_high != null ? `Day range ${money(w.day_low)}–${money(w.day_high)}` : undefined}>
                          {w.symbol}
                        </span>
                      ),
                    },
                    { key: 'price', label: 'Last', align: 'right', render: (w) => (w.price == null ? '—' : money(w.price)) },
                    {
                      key: 'change_pct', label: 'Chg', align: 'right',
                      render: (w) => (w.change == null ? '—' : (
                        <span className={signClass(w.change)} title={`${w.change > 0 ? '+' : w.change < 0 ? '−' : ''}${money(Math.abs(w.change))} vs the previous close`}>
                          {w.change > 0 ? '+' : ''}{w.change_pct.toFixed(2)}%
                        </span>
                      )),
                    },
                    { key: 'iv', label: 'IV', align: 'right', render: (w) => (w.iv == null ? '—' : `${w.iv.toFixed(0)}%`) },
                    { key: 'iv_rank', label: 'Rank', align: 'right', render: (w) => (w.iv_rank == null ? '—' : w.iv_rank.toFixed(0)) },
                  ]}
                />
              </div>
            ) : <p className="summary-line">{watch.error ? 'Prices are unavailable right now.' : 'No tickers to watch.'}</p>}
          </div>

          <div className="card" id="home-events">
            <CardHead title="Upcoming events" sub={`Next ${EVENTS_DAYS} days · US Eastern`} />
            {events.loading ? <Placeholder rows={4} /> : (
              <>
                {eventsShown.length ? (
                  <DataTable
                    data={eventsShown}
                    paginate={false}
                    cards={false}
                    columns={[
                      {
                        key: 'date', label: 'Date',
                        render: (e) => (
                          <span className="home-event-when">
                            {eventDay(e.date)}
                            {e.time && <span className="summary-line">{eventTime(e.time)}</span>}
                          </span>
                        ),
                      },
                      {
                        key: 'name', label: 'Event',
                        render: (e) => (
                          <span className="home-contract">
                            <span className="home-contract-name">
                              {e.name}
                              {e.major && <> <span className="home-chip home-chip--warning">Major</span></>}
                            </span>
                            {e.detail && <span className="home-contract-meta">{e.detail}</span>}
                          </span>
                        ),
                      },
                    ]}
                  />
                ) : <p className="summary-line">Nothing scheduled.</p>}
                {events.notes?.map((n) => <p key={n} className="summary-line">{n}</p>)}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 3. Risk: what expires soon, with the calendar beside it */}
      <div className="home-grid home-grid--wide">
        {!book.loading && !derived?.expiring.length ? (
          <EmptyCard id="home-expiring" title={`Expiring within ${rules['home.expiring_days']} days`} message="No short options expire in that window." />
        ) : (
          <div className="card" id="home-expiring">
            <CardHead title={`Expiring within ${rules['home.expiring_days']} days`} sub="Soonest first" />
            {book.loading ? <Placeholder rows={4} /> : (
              <DataTable
                data={derived.expiring}
                paginate={false}
                cards={EXPIRING_CARDS}
                defaultSortKey="dte"
                columns={[
                  { key: 'key', label: 'Contract', render: contractLabel },
                  { key: 'dte', label: 'DTE', align: 'right' },
                  {
                    key: 'events', label: 'Before expiry',
                    render: (s) => <EventChips events={eventsBefore(eventList, { ticker: s.ticker, type: s.type, expiration: s.expiration })} />,
                  },
                  {
                    key: 'status', label: 'Status',
                    render: (s) => (s.status ? <span className={`home-chip home-chip--${STATUS[s.status].tone}`}>{STATUS[s.status].label}</span> : '—'),
                  },
                  { key: 'distance', label: 'Cushion', align: 'right', render: (s) => (s.distance == null ? '—' : pct(s.distance)) },
                  { key: 'underlyingPrice', label: 'Underlying', align: 'right', render: (s) => money(s.underlyingPrice) },
                  { key: 'pl', label: 'P&L', align: 'right', render: (s) => <span className={signClass(s.pl)}>{money(s.pl, 0)}</span> },
                ]}
              />
            )}
            {derived?.futuresMissing && <p className="summary-line">Futures options couldn't be loaded, so they're left out.</p>}
          </div>
        )}

        {!book.loading && !derived?.calendar.length ? (
          <EmptyCard id="home-calendar" title="Expiry calendar" message={`Nothing expires in the next ${CALENDAR_DAYS} days.`} />
        ) : (
          <div className="card" id="home-calendar">
            <CardHead title="Expiry calendar" sub={`Next ${CALENDAR_DAYS} days`} />
            {book.loading ? <Placeholder rows={4} /> : (
              <DataTable
                data={derived.calendar}
                paginate={false}
                cards={false}
                columns={[
                  { key: 'date', label: 'Date', render: (d) => eventDay(d.date) },
                  { key: 'count', label: 'Shorts', align: 'right' },
                  { key: 'credit', label: 'Premium', align: 'right', render: (d) => money(d.credit, 0) },
                ]}
              />
            )}
          </div>
        )}
      </div>

      {/* 4. Income from what you hold, and profit to take */}
      <div className="home-grid">

        {sharesEmpty ? <EmptyCard id="home-shares" title="Shares to sell against" message="Every share is covered." /> : (
          <div className="card" id="home-shares">
            <CardHead title="Shares to sell against" sub="Shares not yet covered by a short call (long) or short put (short)" />
            {book.loading ? <Placeholder /> : (
              <ul className="home-list">
                {derived.uncovered.map((u) => (
                  <li key={u.ticker}>
                    <span className="home-list-main">{u.ticker}</span>
                    <span>Sell up to {u.contracts} covered {u.side === 'CALL' ? 'call' : 'put'}{u.contracts === 1 ? '' : 's'}</span>
                    <span className="summary-line">{count(u.shares)} shares{u.price != null ? ` at ${money(u.price)}` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {profitEmpty ? <EmptyCard id="home-take-profit" title="Take profit" message={`No short has kept ${rules['home.take_profit_pct']}% of its premium yet.`} /> : (
          <div className="card" id="home-take-profit">
            <CardHead title="Take profit" sub={`Shorts that have kept ${rules['home.take_profit_pct']}% or more of their premium: close and redeploy`} />
            {book.loading ? <Placeholder /> : (
              <DataTable
                data={derived.takeProfit}
                paginate={false}
                cards={TAKE_PROFIT_CARDS}
                columns={[
                  {
                    key: 'key', label: 'Contract',
                    render: (s) => (
                      <span className="home-contract">
                        <span className="home-contract-name">{contractLabel(s)}</span>
                        <span className="home-contract-meta">{s.dte} DTE</span>
                      </span>
                    ),
                  },
                  { key: 'kept', label: 'Kept', align: 'right', render: (s) => <span className="cell-positive">{pct(s.kept, 0)}</span> },
                  { key: 'pl', label: 'P&L', align: 'right', render: (s) => money(s.pl, 0) },
                  { key: 'credit', label: 'Credit', align: 'right', render: (s) => money(s.credit, 0) },
                ]}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// A card's header: title (with an optional "?" pop-up), a one-line
// subtitle, and an optional control on the right.
function CardHead({ title, sub, help, right }) {
  return (
    <div className="home-card-head">
      <div className="home-card-title">
        <h3 className="section-title">
          {title}
          {help && <HelpTip label={`About ${title}`}>{help}</HelpTip>}
        </h3>
        {sub && <span className="summary-line">{sub}</span>}
      </div>
      {right}
    </div>
  )
}

// A card with nothing to show, as one line.
function EmptyCard({ id, title, message }) {
  return (
    <div className="card home-card--empty" id={id}>
      <h3 className="section-title">{title}</h3>
      <span className="summary-line">{message}</span>
    </div>
  )
}

// Placeholder bars in the shape of a loading list, so the page doesn't
// jump as sections arrive.
function Placeholder({ rows = 3 }) {
  return (
    <div className="home-placeholder" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <span key={i} />)}
    </div>
  )
}

// An idea's own stress numbers, for its hover tooltip.
function ideaDetail(r, crashPct, eventCrashPct) {
  const move = `${r.type === 'PUT' ? '−' : '+'}${r.eventCrash ? eventCrashPct : crashPct}%`
  return [
    `Loss if the market moves ${move} at once: ${money(Math.max(0, r.crashLoss), 0)}`,
    `Its margin after that move: ${money(r.crashMargin, 0)}`,
    r.iv ? `Implied volatility ${(r.iv * 100).toFixed(1)}%` : null,
    r.eventCrash ? 'Lives through a major event, so stressed at the larger move' : null,
  ].filter(Boolean).join('\n')
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
