import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getAppConfig, getPositions, getFuturesPosition, getFuturesOptionPosition, getMarketQuotes, getOptionQuotes,
  getAllocations, getEquityTransactions, getIncomeAndFees, screenOptions, getMarketEvents, friendlyErrorMessage,
} from '../api/client'
import {
  ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, LabelList,
} from 'recharts'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'
import { money, count } from '../utils/numberFormat'
import { formatDate } from '../utils/dateFormat'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { closedTrades, compactUsd } from '../utils/reportStats'
import { futuresOptionContracts, futuresOptionRowPl } from '../utils/positionPl'
import { getMultiplier, MULTIPLIER } from '../utils/contractMultiplier'
import {
  futuresMarginEstimate, ideaStress, ideaFit, worstCushion, rootLean, callsCoverLeft, takeProfitCandidates,
  equityShort, eventsBefore, expiringSoon, uncoveredShares, expiryCalendar,
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
  'home.idea_max_dte': 7, 'home.idea_min_delta_pct': 5, 'home.idea_max_delta_pct': 20,
  'home.stress_iv_rise': 20, 'home.idea_crash_pct': 5, 'home.event_crash_pct': 8,
}
const CALENDAR_DAYS = 14
const IDEAS_SHOWN = 8
const EVENTS_DAYS = 14
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

// Margin cushion chart: account equity and margin requirement as the whole
// market falls, from the stress test — the gap is the cushion, and the
// lines cross at the margin call. Out to 30% down, or past the margin call
// if that's further (up to 60%).
function MarginChart({ points, callDrop, callDropRelief }) {
  const last = points.length - 1
  const endLabel = (name) => function EndLabel({ x, y, index }) {
    if (index !== last) return null
    return <text x={x + 8} y={y + 4} className="home-chart-label">{name}</text>
  }
  const depth = points[last].down
  // Whole-number steps on both axes: every 5% down (10% past 30%), and a
  // dollar scale from 0 (or the lowest value, if below 0) to a round top.
  const xTicks = []
  for (let d = 0; d <= depth; d += depth > 30 ? 10 : 5) xTicks.push(d)
  const values = points.flatMap((p) => [p.equity, p.req, p.reqRelief])
  const step = niceStep(Math.max(...values) - Math.min(0, ...values))
  const yMin = Math.min(0, Math.floor(Math.min(...values) / step) * step)
  const yMax = Math.ceil(Math.max(...values) / step) * step
  const yTicks = []
  for (let v = yMin; v <= yMax + 1e-6; v += step) yTicks.push(v)
  const EquityLabel = endLabel('Equity')
  const ReqLabel = endLabel('Margin req')
  const ReliefLabel = endLabel('with relief')
  return (
    <div className="home-chart">
      <div className="home-chart-legend" aria-hidden="true">
        <span><i style={{ background: 'var(--chart-equity)' }} />Equity</span>
        <span><i style={{ background: 'var(--chart-req)' }} />Margin requirement</span>
        <span><i className="home-chart-legend-relief" />Requirement if it eases with prices</span>
        {callDrop != null && (
          <span>
            <i className="home-chart-legend-call" />
            Margin call{callDropRelief != null && callDropRelief !== callDrop ? ` (−${callDropRelief.toFixed(1)}% if it eases)` : ''}
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={points} margin={{ top: 16, right: 84, left: 4, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="down" type="number" domain={[0, depth]} ticks={xTicks} interval={0}
            tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={{ stroke: 'var(--border-strong)' }}
            tickFormatter={(d) => (d === 0 ? '0%' : `−${d}%`)} height={24}
          />
          <YAxis
            type="number" domain={[yMin, yMax]} ticks={yTicks} interval={0} allowDataOverflow={false}
            tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} width={64} tickFormatter={compactUsd}
          />
          {callDrop != null && (
            <ReferenceLine x={callDrop} stroke="var(--error)" strokeDasharray="4 4"
              label={{ value: `Margin call −${callDrop.toFixed(1)}%`, position: 'insideTopLeft', fontSize: 11, fill: 'var(--text)' }} />
          )}
          <Tooltip
            cursor={{ stroke: 'var(--border-strong)', strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const p = payload[0].payload
              return (
                <div className="chart-tooltip report-tooltip">
                  <div className="report-tooltip-title">Market {p.down === 0 ? 'today' : `down ${p.down}%`}</div>
                  <div className="report-tooltip-row"><span>Equity</span><span>{money(p.equity, 0)}</span></div>
                  <div className="report-tooltip-row"><span>Margin requirement</span><span>{money(p.req, 0)}</span></div>
                  <div className="report-tooltip-row"><span>Cushion</span><span className={p.cushion < 0 ? 'cell-negative' : ''}>{money(p.cushion, 0)}</span></div>
                  <div className="report-tooltip-row"><span>Requirement if it eases</span><span>{money(p.reqRelief, 0)}</span></div>
                  <div className="report-tooltip-row"><span>Cushion if it eases</span><span className={p.cushionRelief < 0 ? 'cell-negative' : ''}>{money(p.cushionRelief, 0)}</span></div>
                </div>
              )
            }}
          />
          <Line dataKey="equity" name="Equity" type="monotone" stroke="var(--chart-equity)" strokeWidth={2} dot={false}
            activeDot={{ r: 4.5, fill: 'var(--chart-equity)', stroke: 'var(--card-bg)', strokeWidth: 2 }} isAnimationActive={false}>
            <LabelList dataKey="equity" content={<EquityLabel />} />
          </Line>
          <Line dataKey="req" name="Margin requirement" type="monotone" stroke="var(--chart-req)" strokeWidth={2} dot={false}
            activeDot={{ r: 4.5, fill: 'var(--chart-req)', stroke: 'var(--card-bg)', strokeWidth: 2 }} isAnimationActive={false}>
            <LabelList dataKey="req" content={<ReqLabel />} />
          </Line>
          <Line dataKey="reqRelief" name="Requirement if it eases" type="monotone" stroke="var(--chart-req)" strokeWidth={2}
            strokeDasharray="2 4" strokeLinecap="round" dot={false}
            activeDot={{ r: 4, fill: 'var(--card-bg)', stroke: 'var(--chart-req)', strokeWidth: 2 }} isAnimationActive={false}>
            <LabelList dataKey="reqRelief" content={<ReliefLabel />} />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
      <div className="home-chart-axis">Market down</div>
    </div>
  )
}

// A round step (1, 2 or 5 x a power of ten) giving about five ticks over `span`.
function niceStep(span) {
  if (!(span > 0)) return 1
  const raw = span / 5
  const pow = 10 ** Math.floor(Math.log10(raw))
  const f = raw / pow
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow
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
    const callDrop = cushion == null ? null : marginCallMove(cushion, stress, -1, stressOptions)
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
      calendar: expiryCalendar(shorts, CALENDAR_DAYS),
      cushion,
      fundsFromSettings,
      unpricedRisk: stress.unpriced,
      stress: cushion == null ? [] : STRESS_MOVES.map((move) => ({ move, after: cushion + cushionChange(stress, move, stressOptions).change })),
      // For the new-income ideas, judged against this book.
      stressBook: stress,
      stressOptions,
      lean: rootLean(stress.positions),
      coverLeft: callsCoverLeft(stress.positions),
      // Equity and requirement as the market falls, for the chart: today's
      // requirement is the margin used (Schwab's + the futures estimate),
      // equity is that plus the cushion.
      chart: cushion == null ? [] : (() => {
        const callPct = callDrop == null ? null : -callDrop * 100
        const depth = Math.min(60, Math.max(30, callPct == null ? 0 : Math.ceil(callPct / 5) * 5 + 5))
        const req0 = maint + futMargin.total
        const points = []
        for (let down = 0; down <= depth; down++) {
          const c = cushionChange(stress, -down / 100, stressOptions)
          const r = cushionChange(stress, -down / 100, { ...stressOptions, relief: true })
          points.push({
            down, equity: cushion + req0 + c.pnl, req: req0 + c.reqRise, cushion: cushion + c.change,
            reqRelief: req0 + r.reqRise, cushionRelief: cushion + r.change,
          })
        }
        return points
      })(),
      callDrop,
      // The same with requirements allowed to fall — the chart's dotted line.
      callDropRelief: cushion == null ? null : marginCallMove(cushion, stress, -1, { ...stressOptions, relief: true }),
      callRally: cushion == null ? null : marginCallMove(cushion, stress, 1, stressOptions),
    }
  }, [book, rules])

  const marginPct = rules['home.futures_margin_pct']
  const funds = derived?.cushion ?? null
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

  return (
    <div className="page home">
      <div className="home-head">
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

      {/* Margin cushion and upcoming events, side by side */}
      <div className="home-grid home-grid--wide">
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
            {derived.chart.length > 0 && (
              <MarginChart
                points={derived.chart}
                callDrop={derived.callDrop == null ? null : -derived.callDrop * 100}
                callDropRelief={derived.callDropRelief == null ? null : -derived.callDropRelief * 100}
              />
            )}
            {derived.unpricedRisk > 0 && (
              <p className="summary-line">
                {derived.unpricedRisk} position{derived.unpricedRisk === 1 ? '' : 's'} with no price {derived.unpricedRisk === 1 ? 'is' : 'are'} left out of the stress test.
              </p>
            )}
          </>
        ) : <p className="summary-line">Schwab didn't return available funds.</p>}
      </div>

      {/* Upcoming events: what could move the market before shorts expire */}
      <div className="card">
        <div className="home-card-head">
          <h3 className="section-title">Upcoming events · next {EVENTS_DAYS} days</h3>
          <span className="summary-line">Times are US Eastern</span>
        </div>
        {events.loading ? <Spinner /> : (() => {
          const shown = eventList
            .filter((e) => e.date <= iso(new Date(Date.now() + EVENTS_DAYS * 86400000)))
            .sort((a, b) => a.date.localeCompare(b.date) || (a.time ?? '99:99').localeCompare(b.time ?? '99:99'))
          return (
            <>
              {shown.length ? (
                <ul className="home-list home-events">
                  {shown.map((e) => (
                    <li key={`${e.date}|${e.name}`}>
                      <span className="home-event-when">
                        {eventDay(e.date)}
                        {e.time && <span className="summary-line">{eventTime(e.time)}</span>}
                      </span>
                      <span className="home-list-main">
                        {e.name}
                        {e.major && <> <span className="home-chip home-chip--warning">Major</span></>}
                      </span>
                      <span className="summary-line">{e.detail ?? ''}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="summary-line">Nothing scheduled.</p>}
              {events.notes?.map((n) => <p key={n} className="summary-line">{n}</p>)}
            </>
          )
        })()}
      </div>
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
                    {ideaSide === 'CALL' && ` · ${derived.coverLeft[root] ?? 0} uncovered for calls`}
                  </span>
                )}
              </div>
            )
          })}
        </div>
        <p className="summary-line">
          Expiring within {rules['home.idea_max_dte']} days, delta {(rules['home.idea_min_delta_pct'] / 100).toFixed(2)}–{(rules['home.idea_max_delta_pct'] / 100).toFixed(2)},
          judged against your positions as if the market moves {crashPct}% or {2 * crashPct}% either way at once ({eventCrashPct}% or {2 * eventCrashPct}% for one that lives through CPI, jobs, PCE or an FOMC decision) — trades that offset them first.
          {worstNow != null && (worstNow > 0
            ? ` Worst cushion after those moves today: ${money(worstNow, 0)}.`
            : ` Those moves would already leave no cushion (${money(worstNow, 0)}) — only trades that offset your risk fit.`)}
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
                { key: 'events', label: 'Before expiry', render: (r) => <EventChips events={r.events} /> },
                { key: 'otmPct', label: 'OTM', align: 'right', render: (r) => pct(r.otmPct) },
                { key: 'delta', label: 'Delta', align: 'right', render: (r) => (r.delta == null ? '—' : Math.abs(r.delta).toFixed(2)) },
                { key: 'credit', label: 'Credit', align: 'right', render: (r) => money(r.credit) },
                {
                  key: 'crashLoss', label: `Loss at ${ideaSide === 'PUT' ? '−' : '+'}${crashPct}%`, align: 'right',
                  render: (r) => (
                    <span className={r.crashLoss > 0 ? 'cell-negative' : ''} title={r.eventCrash ? `At ${eventCrashPct}%: it lives through a major event` : undefined}>
                      {money(Math.max(0, r.crashLoss), 0)}{r.eventCrash ? ` (${eventCrashPct}%)` : ''}
                    </span>
                  ),
                },
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

      {/* 4. Risk: what expires soon, with the calendar beside it */}
      <div className="home-grid home-grid--wide">
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
                key: 'events', label: 'Before expiry',
                render: (s) => <EventChips events={eventsBefore(eventList, { ticker: s.ticker, type: s.type, expiration: s.expiration })} />,
              },
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
