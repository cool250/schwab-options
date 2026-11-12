import { useMemo, useState } from 'react'
import {
  ResponsiveContainer, ComposedChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'
import { placedTradeStats, pct } from '../utils/reportStats'
import { marketDays } from '../utils/marketCalendar'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { formatDate } from '../utils/dateFormat'

/*
 * Reports' Trade Details tab: the trades the account holder placed — the
 * activity that counts toward trader tax status (TTS). Expirations,
 * assignments, exercises and what they deliver aren't trades you placed and
 * are left out (the backend keeps only executions with an order behind
 * them), as are money-market sweeps. Key numbers, trades and trading days
 * by month, a monthly table and the full trade log. The math is
 * placedTradeStats() in utils/reportStats.js; series colors are the
 * --series-* tokens.
 */

const axisTick = { fontSize: 11, fill: 'var(--text-muted)' }
const count = (n) => (n ?? 0).toLocaleString('en-US')
const days = (n) => `${Number.isInteger(n) ? n : n.toFixed(n < 10 ? 1 : 0)} day${n === 1 ? '' : 's'}`

const TRADE_SERIES = [
  { key: 'options', label: 'Options', color: 'var(--series-1)' },
  { key: 'futures', label: 'Futures', color: 'var(--series-2)' },
  { key: 'stocks', label: 'Stock & ETF', color: 'var(--series-3)' },
]
const DAY_SERIES = [
  { key: 'daysTraded', label: 'Days traded', color: 'var(--series-1)' },
  { key: 'marketDays', label: 'Market days', color: 'var(--series-5)' },
]

function Legend({ series }) {
  return (
    <div className="report-legend">
      {series.map((s) => (
        <span key={s.key}><i className="report-key-bar" style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  )
}

/** Months across; stacked: one stack of the series, else side by side. */
function MonthBars({ data, series, stacked, total, onMonth, label }) {
  return (
    <div className="report-chart-fill" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%" minHeight={260}>
        <ComposedChart
          data={data}
          margin={{ top: 12, right: 8, left: 0, bottom: 0 }}
          onClick={(s) => s?.activePayload?.length && onMonth(s.activePayload[0].payload.m)}
          style={{ cursor: 'pointer' }}
        >
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} interval={0} />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={40} tickFormatter={count} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: 'var(--bg)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const p = payload[0].payload
              const rows = [...series.map((s) => [s.label, count(p[s.key])]), ...(total ? [total(p)] : [])]
              return (
                <div className="chart-tooltip report-tooltip">
                  <div className="report-tooltip-title">{p.label}</div>
                  {rows.map(([k, v]) => (
                    <div key={k} className="report-tooltip-row"><span>{k}</span><span>{v}</span></div>
                  ))}
                </div>
              )
            }}
          />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId={stacked ? 'a' : undefined}
              fill={s.color} maxBarSize={stacked ? 36 : 18} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// "Sell to open", "Buy to close" — or plain Buy / Sell where the broker
// gives no reliable label (futures).
function action(t) {
  const side = t.quantity > 0 ? 'Buy' : 'Sell'
  if (t.asset_class === 'FUTURE' || !t.position_effect) return side
  return `${side} to ${t.position_effect === 'OPENING' ? 'open' : 'close'}`
}

function symbolOf(t) {
  if (t.asset_class === 'OPTION') {
    return formatOptionSymbol(t.underlying, t.expiration, t.strike, t.option_type) ?? t.symbol
  }
  return t.symbol
}

const timeOf = (t) => (t.time ? new Date(t.time).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '')

const ASSET_LABELS = { OPTION: 'Option', FUTURE: 'Future', STOCK: 'Stock', ETF: 'ETF' }

// The trade log as a CSV file, for a tax adviser or a spreadsheet: one row
// per trade placed, the same columns as the table plus the asset and its
// underlying. Quantity is signed (negative = sold).
function downloadCsv(trades, start, end) {
  const cell = (v) => {
    const s = v == null ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const rows = [
    ['Date', 'Time', 'Symbol', 'Underlying', 'Asset', 'Action', 'Quantity', 'Price', 'Order ID'],
    ...trades.map((t) => [
      t.date, timeOf(t), symbolOf(t), t.underlying, ASSET_LABELS[t.asset_class] ?? t.asset_class,
      action(t), t.quantity, t.price, t.order_id,
    ]),
  ]
  const blob = new Blob([rows.map((r) => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `trades-placed-${start}-to-${end}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function TradeLog({ trades }) {
  return (
    <div className="report-table-wrap">
      <table className="report-table trade-log-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Time</th>
            <th>Symbol</th>
            <th>Action</th>
            <th className="num">Qty</th>
            <th className="num">Price</th>
            <th className="num">Order</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              <td>{formatDate(t.date)}</td>
              <td>{timeOf(t)}</td>
              <td className="report-sym">{symbolOf(t)}</td>
              <td>{action(t)}</td>
              <td className="num">{count(Math.abs(t.quantity))}</td>
              <td className="num">{t.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
              <td className="num trade-log-order">{t.order_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * placed: GET /portfolio/transactions/placed-trades ({ trades, not_placed }),
 * or null when it didn't load. closedTrades: the period's realized trades
 * (for the holding period). start / end: the period ("YYYY-MM-DD");
 * lastMonth: last month shown (0-based); label: "2026 year to date";
 * onMonth(m): open that month's transactions.
 */
export default function TradeDetails({ placed, closedTrades, start, end, lastMonth, label, onMonth }) {
  const [showLog, setShowLog] = useState(false)
  const trades = placed?.trades ?? []
  const { months, total, holding } = useMemo(
    () => placedTradeStats({ trades, closedTrades, marketDays: marketDays(start, end), lastMonth }),
    [trades, closedTrades, start, end, lastMonth],
  )

  if (!placed) return <div className="alert error">The trades you placed couldn’t be loaded. Try again in a moment.</div>

  const weeks = total.marketDays / 5
  const tiles = [
    {
      label: 'Trades placed',
      value: count(total.trades),
      sub: <>in {count(total.orders)} orders<span className="report-kpi-subline">{count(total.opening)} opening · {count(total.closing)} closing</span></>,
      hero: true,
    },
    {
      label: 'Days traded',
      value: <>{count(total.daysTraded)} <span className="report-kpi-inline">of {count(total.marketDays)} market days</span></>,
      sub: `${pct(total.marketDays ? total.daysTraded / total.marketDays : null)} of trading days`,
    },
    {
      label: 'Trade frequency',
      value: total.daysTraded ? (total.trades / total.daysTraded).toFixed(1) : '—',
      sub: <>trades per day traded<span className="report-kpi-subline">{weeks ? (total.trades / weeks).toFixed(1) : '—'} per week</span></>,
    },
    {
      label: 'Holding period',
      value: holding ? days(holding.avg) : '—',
      sub: holding ? <>average · median {days(holding.median)}<span className="report-kpi-subline">{count(holding.n)} closed trades</span></> : 'No closed trades',
    },
  ]

  return (
    <>
      <div className="card">
        <div className="report-kpis report-kpis--all">
          {tiles.map((t) => (
            <div key={t.label} className={`report-kpi${t.hero ? ' report-kpi--hero' : ''}`}>
              <span className="report-kpi-label">{t.label}</span>
              <span className="report-kpi-value">{t.value}</span>
              {t.sub && <span className="report-kpi-sub">{t.sub}</span>}
            </div>
          ))}
        </div>
        <p className="report-footnote">
          Only trades you placed: each executed leg of an order (a two-leg spread is two trades). Not counted —{' '}
          {count(placed.not_placed)} expirations, assignments, exercises and the shares or futures they delivered,
          and money-market sweeps.
        </p>
      </div>

      <div className="report-row trade-details-row">
        <div className="card">
          <div className="report-card-head">
            <h3 className="section-title">Trades placed by month</h3>
            <span className="report-card-note">Click a month for its transactions</span>
          </div>
          <Legend series={TRADE_SERIES} />
          <MonthBars data={months} series={TRADE_SERIES} stacked onMonth={onMonth}
            total={(p) => ['Total', count(p.trades)]}
            label={`Trades placed each month by asset, ${label}`} />
        </div>

        <div className="card">
          <div className="report-card-head">
            <h3 className="section-title">Days traded by month</h3>
            <span className="report-card-note">Out of the NYSE trading days</span>
          </div>
          <Legend series={DAY_SERIES} />
          <MonthBars data={months} series={DAY_SERIES} onMonth={onMonth}
            total={(p) => ['Share', pct(p.marketDays ? p.daysTraded / p.marketDays : null)]}
            label={`Days with a trade placed each month, beside that month's market days, ${label}`} />
        </div>
      </div>

      <div className="card trade-details-card">
        <div className="report-card-head">
          <h3 className="section-title">By month</h3>
          <span className="report-card-note">Click a month for its transactions</span>
        </div>
        <div className="report-table-wrap">
          <table className="report-table trade-details-table">
            <thead>
              <tr>
                <th>Month</th>
                {['Trades', 'Orders', 'Opening', 'Closing', 'Options', 'Futures', 'Stock & ETF', 'Days traded', 'Market days', '% of days']
                  .map((h) => <th key={h} className="num">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {months.map((r) => (
                <tr key={r.m} className="report-row-link" tabIndex={0} onClick={() => onMonth(r.m)}
                  onKeyDown={(e) => { if (e.key === 'Enter') onMonth(r.m) }}>
                  <td className="report-sym">{r.label}</td>
                  <MonthCells r={r} />
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <MonthCells r={total} />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <div className={`card trade-details-card${showLog ? '' : ' no-print'}`}>
        <div className="report-card-head">
          <h3 className="section-title">Trade log</h3>
          <div className="report-card-actions no-print">
            <button type="button" className="btn btn-secondary" onClick={() => downloadCsv(trades, start, end)}>
              Download CSV
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog}>
              {showLog ? 'Hide' : `Show all ${count(total.trades)}`}
            </button>
          </div>
        </div>
        {showLog
          ? <TradeLog trades={trades} />
          : <p className="summary-line">Every trade placed, oldest first. Shown here, it&apos;s also included in Export PDF; Download CSV saves it for a spreadsheet or your tax adviser.</p>}
      </div>
    </>
  )
}

function MonthCells({ r }) {
  return (
    <>
      {[r.trades, r.orders, r.opening, r.closing, r.options, r.futures, r.stocks, r.daysTraded, r.marketDays]
        .map((v, i) => <td key={i} className="num">{count(v)}</td>)}
      <td className="num">{pct(r.marketDays ? r.daysTraded / r.marketDays : null)}</td>
    </>
  )
}
