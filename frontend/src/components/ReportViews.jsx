import { useMemo } from 'react'
import {
  ResponsiveContainer, ComposedChart, BarChart, AreaChart, Bar, Line, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, LabelList,
} from 'recharts'
import {
  MONTH_NAMES, tradeStats, sumBy, countBy, runningTotal, pnlStep, symbolOf,
  utcDate, addDays, mondayOf, longDate, usd, signedUsd, compactUsd, pct, signClass,
} from '../utils/reportStats'

/*
 * The Reports page's views (pages/Reports.jsx): a key-numbers strip, a
 * month P&L calendar, a running total over daily bars, per-symbol tables,
 * and the YTD monthly bars / running total / symbol-by-month table /
 * every-trading-day calendar. Gain/loss heat colors are the --pnl-* tokens
 * in tokens.css (a diverging pair with a neutral midpoint).
 */

// ---------------------------------------------------------------- shared

/** Recharts bar with a 4px rounded data-end, square at the baseline — for
 *  gains and losses alike (a loss rounds at the bottom). */
function PnlBar({ x, y, width, height, value }) {
  const v = Array.isArray(value) ? value[1] - value[0] : value
  if (!height || !width) return null
  const top = height < 0 ? y + height : y
  const h = Math.abs(height)
  const r = Math.min(4, h, width / 2)
  const fill = v >= 0 ? 'var(--success)' : 'var(--error)'
  const d = v >= 0
    ? `M${x},${top + h}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${top + h}Z`
    : `M${x},${top}V${top + h - r}Q${x},${top + h} ${x + r},${top + h}H${x + width - r}Q${x + width},${top + h} ${x + width},${top + h - r}V${top}Z`
  return <path d={d} fill={fill} />
}

function TooltipCard({ title, rows }) {
  return (
    <div className="chart-tooltip report-tooltip">
      <div className="report-tooltip-title">{title}</div>
      {rows.map(([k, v, cls]) => (
        <div key={k} className="report-tooltip-row">
          <span>{k}</span>
          <span className={cls}>{v}</span>
        </div>
      ))}
    </div>
  )
}

const axisTick = { fontSize: 11, fill: 'var(--text-muted)' }

/** Text label at the last point of a series only (an end label, not a
 *  number on every point). */
function endLabel(count, format) {
  return function EndLabel({ x, y, index, value }) {
    if (index !== count - 1) return null
    return (
      <text x={x + 9} y={y + 4} className="report-end-label">
        {format(value)}
      </text>
    )
  }
}

export function HeatScale({ maxAbs }) {
  if (!maxAbs) return null
  return (
    <div className="pnl-scale" aria-label={`Color scale from a ${usd(-maxAbs)} loss to a ${usd(maxAbs)} gain`}>
      <span>Loss {compactUsd(-maxAbs)}</span>
      <span className="pnl-scale-swatches">
        {[4, 3, 2, 1].map((n) => <i key={`l${n}`} style={{ background: `var(--pnl-loss-${n})` }} />)}
        <i style={{ background: 'var(--pnl-neutral)' }} />
        {[1, 2, 3, 4].map((n) => <i key={`g${n}`} style={{ background: `var(--pnl-gain-${n})` }} />)}
      </span>
      <span>Gain {compactUsd(maxAbs)}</span>
    </div>
  )
}

/** Enter/Space activate a non-button clickable element, like a button. */
const keyActivate = (fn) => (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() }
}

// ---------------------------------------------------------------- key numbers

/**
 * stats: tradeStats() of this period. prev: tradeStats() of the comparison
 * period (or null). extraNet: equity/futures P&L to mention under the net
 * (or 0).
 */
export function KpiStrip({ stats, prev, prevName, netNote, extraNet = 0 }) {
  const delta = prev ? stats.net - prev.net : null
  const tiles = [
    {
      label: 'Option P&L',
      value: <span className={signClass(stats.net)}>{usd(stats.net)}</span>,
      sub: delta != null
        ? <><span className={signClass(delta)}>{delta >= 0 ? '▲' : '▼'} {usd(Math.abs(delta))}</span> vs {prevName}</>
        : netNote,
      hero: true,
    },
    { label: 'Trades closed', value: stats.n.toLocaleString(), sub: prev ? `${prev.n} in ${prevName}` : '' },
    { label: 'Win rate', value: pct(stats.winRate), sub: prev ? `${pct(prev.winRate)} in ${prevName}` : '' },
    { label: 'Avg win', value: <span className="pnl-up">{usd(stats.avgWin)}</span>, sub: 'per winning trade' },
    { label: 'Avg loss', value: <span className="pnl-down">{usd(stats.avgLoss)}</span>, sub: 'per losing trade' },
    {
      label: 'Profit factor',
      value: stats.profitFactor == null ? '—' : stats.profitFactor.toFixed(2),
      sub: 'gross wins ÷ gross losses',
    },
  ]
  return (
    <div className="card">
      <div className="report-kpis">
        {tiles.map((t) => (
          <div key={t.label} className={`report-kpi${t.hero ? ' report-kpi--hero' : ''}`}>
            <span className="report-kpi-label">{t.label}</span>
            <span className="report-kpi-value">{t.value}</span>
            {t.sub && <span className="report-kpi-sub">{t.sub}</span>}
          </div>
        ))}
      </div>
      {extraNet !== 0 && (
        <p className="summary-line report-kpi-extra">
          Equity/futures: <span className={signClass(extraNet)}>{usd(extraNet)}</span>
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- month calendar

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

/** Mon–Fri grid of one month's trading days, each shaded by its P&L, with
 *  the week's total at the end of each row. month: 1-12. */
export function MonthCalendar({ year, month, trades, today, onDay, onWeek }) {
  const { weeks, maxAbs } = useMemo(() => {
    const daily = sumBy(trades, (t) => t.close_date)
    const counts = countBy(trades, (t) => t.close_date)
    const first = `${year}-${String(month).padStart(2, '0')}-01`
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
    const last = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
    const out = []
    for (let mon = mondayOf(first); mon <= last; mon = addDays(mon, 7)) {
      const days = WEEKDAYS.map((_, i) => {
        const date = addDays(mon, i)
        return { date, inMonth: date >= first && date <= last, future: date > today, value: daily.get(date), count: counts.get(date) ?? 0 }
      })
      if (days.every((d) => !d.inMonth)) continue // a week of only weekend days of this month
      const traded = days.filter((d) => d.inMonth && d.value != null)
      out.push({ monday: mon, days, total: traded.reduce((s, d) => s + d.value, 0), tradedDays: traded.length })
    }
    return { weeks: out, maxAbs: Math.max(0, ...[...daily.values()].map(Math.abs)) }
  }, [year, month, trades, today])

  return (
    <>
      <div className="pnl-cal" role="grid" aria-label="P&L by trading day">
        {WEEKDAYS.map((d) => <div key={d} className="pnl-cal-head" role="columnheader">{d}</div>)}
        <div className="pnl-cal-head pnl-cal-head--week" role="columnheader">Week</div>
        {weeks.map((w) => (
          <div key={w.monday} className="pnl-cal-row" role="row">
            {w.days.map((d) => {
              const dayNum = utcDate(d.date).getUTCDate()
              if (!d.inMonth) {
                return <div key={d.date} className="pnl-day pnl-day--out" role="gridcell"><span className="pnl-day-num">{MONTH_NAMES[utcDate(d.date).getUTCMonth()]} {dayNum}</span></div>
              }
              if (d.future) {
                return <div key={d.date} className="pnl-day pnl-day--future" role="gridcell"><span className="pnl-day-num">{dayNum}</span></div>
              }
              const step = pnlStep(d.value, maxAbs)
              const label = d.value == null
                ? `${longDate(d.date)}: no trades closed`
                : `${longDate(d.date)}: ${signedUsd(d.value)}, ${d.count} trade${d.count === 1 ? '' : 's'}`
              return (
                <button
                  key={d.date}
                  type="button"
                  role="gridcell"
                  className={`pnl-day${d.value == null ? ' pnl-day--empty' : ''}`}
                  style={step ?? undefined}
                  title={label}
                  aria-label={label}
                  onClick={() => onDay(d.date)}
                >
                  <span className="pnl-day-num">{dayNum}</span>
                  <span className="pnl-day-value">{d.value == null ? '—' : compactUsd(d.value)}</span>
                </button>
              )
            })}
            {w.tradedDays ? (
              <button
                type="button"
                role="gridcell"
                className="pnl-week"
                title={`Week of ${longDate(w.monday)}: ${signedUsd(w.total)}`}
                onClick={() => onWeek(w.monday, addDays(w.monday, 6))}
              >
                <span className={`pnl-week-value ${signClass(w.total)}`}>
                  <span className="pnl-full">{signedUsd(w.total)}</span>
                  <span className="pnl-short">{w.total > 0 ? '+' : ''}{compactUsd(w.total)}</span>
                </span>
                <span className="pnl-week-days">{w.tradedDays} day{w.tradedDays === 1 ? '' : 's'}</span>
              </button>
            ) : (
              <div className="pnl-week pnl-week--empty" role="gridcell">—</div>
            )}
          </div>
        ))}
      </div>
      <HeatScale maxAbs={maxAbs} />
    </>
  )
}

// ---------------------------------------------------------------- month running total

/** Daily P&L as gain/loss bars with the running total as a line — one y-axis. */
export function DailyRunChart({ trades, onDay }) {
  const data = useMemo(() => {
    const counts = countBy(trades, (t) => t.close_date)
    return runningTotal(trades).map((p) => ({ ...p, count: counts.get(p.date) ?? 0 }))
  }, [trades])
  if (data.length === 0) return null
  const EndLabel = endLabel(data.length, compactUsd)
  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart
        data={data}
        margin={{ top: 12, right: 64, left: 0, bottom: 0 }}
        onClick={(s) => s?.activeLabel && onDay(s.activeLabel)}
        style={{ cursor: 'pointer' }}
      >
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="date" tick={axisTick} tickLine={false} axisLine={false} minTickGap={20} tickFormatter={(d) => `${d.slice(5, 7)}/${d.slice(8)}`} />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={56} tickFormatter={compactUsd} />
        <ReferenceLine y={0} stroke="var(--border-strong)" />
        <Tooltip
          cursor={{ stroke: 'var(--border-strong)', strokeWidth: 1, fill: 'none' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const p = payload[0].payload
            return (
              <TooltipCard
                title={longDate(p.date)}
                rows={[
                  ['That day', signedUsd(p.day), signClass(p.day)],
                  ['Running total', usd(p.total), signClass(p.total)],
                  ['Trades', String(p.count)],
                ]}
              />
            )
          }}
        />
        <Bar dataKey="day" name="Daily P&L" maxBarSize={24} shape={<PnlBar />} isAnimationActive={false} />
        <Line
          dataKey="total"
          name="Running total"
          type="linear"
          stroke="var(--primary)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4.5, fill: 'var(--primary)', stroke: 'var(--card-bg)', strokeWidth: 2 }}
          isAnimationActive={false}
        >
          <LabelList dataKey="total" content={<EndLabel />} />
        </Line>
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// ---------------------------------------------------------------- symbol table

/** Per-symbol trades / win rate / average / share of gains / net, with the
 *  net drawn as a bar on one scale for gains and losses. */
export function SymbolTable({ rows, onSymbol }) {
  if (rows.length === 0) return null
  const maxPos = Math.max(0, ...rows.map((r) => r.net))
  const maxNeg = Math.max(0, ...rows.map((r) => -r.net))
  const span = maxPos + maxNeg || 1
  const zero = (maxNeg / span) * 100
  const total = rows.reduce(
    (acc, r) => ({ n: acc.n + r.n, net: acc.net + r.net, wins: acc.wins + (r.winRate ?? 0) * r.n }),
    { n: 0, net: 0, wins: 0 }
  )
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="num">Trades</th>
            <th className="num">Win rate</th>
            <th className="num">Avg P&amp;L</th>
            <th className="num">Share of gains</th>
            <th className="num report-net-col">Net P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const w = (Math.abs(r.net) / span) * 100
            return (
              <tr key={r.symbol} className="report-row-link" tabIndex={0} onClick={() => onSymbol(r.symbol)} onKeyDown={keyActivate(() => onSymbol(r.symbol))} title={`Open ${r.symbol} transactions`}>
                <td className="report-sym">{r.symbol}</td>
                <td className="num">{r.n}</td>
                <td className="num">{pct(r.winRate)}</td>
                <td className={`num ${signClass(r.net)}`}>{usd(r.n ? r.net / r.n : null)}</td>
                <td className="num">{r.shareOfGains == null ? '—' : pct(r.shareOfGains)}</td>
                <td className="num">
                  <div className="report-barcell">
                    <span className="report-track">
                      {maxNeg > 0 && <b style={{ left: `${zero}%` }} />}
                      <i
                        className={r.net < 0 ? 'neg' : ''}
                        style={{ left: `${r.net < 0 ? zero - w : zero}%`, width: `${w}%`, background: r.net < 0 ? 'var(--error)' : 'var(--success)' }}
                      />
                    </span>
                    <span className={`report-amt ${signClass(r.net)}`}>{usd(r.net)}</span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td className="report-sym">Total</td>
            <td className="num">{total.n}</td>
            <td className="num">{pct(total.n ? total.wins / total.n : null)}</td>
            <td className={`num ${signClass(total.net)}`}>{usd(total.n ? total.net / total.n : null)}</td>
            <td />
            <td className="num"><span className={`report-amt ${signClass(total.net)}`}>{usd(total.net)}</span></td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- YTD

/** One gain/loss column per month (0-based months 0..lastMonth); only the
 *  best and worst months are labeled — the tooltip and table carry the rest. */
export function MonthlyBarsChart({ trades, lastMonth, partialNote, onMonth }) {
  const data = useMemo(() => {
    const out = []
    for (let m = 0; m <= lastMonth; m++) {
      const st = tradeStats(trades.filter((t) => utcDate(t.close_date).getUTCMonth() === m))
      out.push({ m, label: MONTH_NAMES[m], net: st.net, n: st.n, winRate: st.winRate })
    }
    return out
  }, [trades, lastMonth])
  const nets = data.map((d) => d.net)
  const iMax = nets.indexOf(Math.max(...nets))
  const iMin = nets.indexOf(Math.min(...nets))
  const ExtremeLabel = ({ x, y, width, height, index, value }) => {
    if ((index !== iMax && index !== iMin) || !value) return null
    const below = value < 0
    const top = height < 0 ? y + height : y
    return (
      <text x={x + width / 2} y={below ? top + Math.abs(height) + 14 : top - 6} textAnchor="middle" className="report-end-label">
        {compactUsd(value)}
      </text>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 20, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={56} tickFormatter={compactUsd} />
        <ReferenceLine y={0} stroke="var(--border-strong)" />
        <Tooltip
          cursor={{ fill: 'var(--bg)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const p = payload[0].payload
            return (
              <TooltipCard
                title={p.m === lastMonth && partialNote ? `${p.label} (${partialNote})` : p.label}
                rows={[['P&L', signedUsd(p.net), signClass(p.net)], ['Trades', String(p.n)], ['Win rate', pct(p.winRate)]]}
              />
            )
          }}
        />
        <Bar dataKey="net" maxBarSize={28} shape={<PnlBar />} cursor="pointer" onClick={(d) => onMonth(d.m)} isAnimationActive={false}>
          <LabelList dataKey="net" content={<ExtremeLabel />} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Cumulative realized P&L across the year, one point per trading day. */
export function CumulativeChart({ trades }) {
  const data = useMemo(() => runningTotal(trades), [trades])
  const monthTicks = useMemo(() => {
    const seen = new Set()
    return data.filter((p) => { const m = p.date.slice(0, 7); if (seen.has(m)) return false; seen.add(m); return true }).map((p) => p.date)
  }, [data])
  if (data.length === 0) return null
  const EndLabel = endLabel(data.length, compactUsd)
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 20, right: 64, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="date" ticks={monthTicks} tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(d) => MONTH_NAMES[utcDate(d).getUTCMonth()]} />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={56} tickFormatter={compactUsd} />
        <ReferenceLine y={0} stroke="var(--border-strong)" />
        <Tooltip
          cursor={{ stroke: 'var(--border-strong)', strokeWidth: 1 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const p = payload[0].payload
            return <TooltipCard title={longDate(p.date)} rows={[['Running total', usd(p.total), signClass(p.total)], ['That day', signedUsd(p.day), signClass(p.day)]]} />
          }}
        />
        <Area
          dataKey="total"
          type="linear"
          stroke="var(--primary)"
          strokeWidth={2}
          fill="var(--primary)"
          fillOpacity={0.1}
          activeDot={{ r: 4.5, fill: 'var(--primary)', stroke: 'var(--card-bg)', strokeWidth: 2 }}
          isAnimationActive={false}
        >
          <LabelList dataKey="total" content={<EndLabel />} />
        </Area>
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Symbols down the side, months across, each cell shaded by its P&L. */
export function SymbolMonthHeat({ trades, lastMonth, onCell, onMonth }) {
  const { symbols, cell, monthTotals, symbolTotals, maxAbs, grand } = useMemo(() => {
    const monthOf = (t) => utcDate(t.close_date).getUTCMonth()
    const cell = sumBy(trades, (t) => `${symbolOf(t)}|${monthOf(t)}`)
    const symbolTotals = sumBy(trades, symbolOf)
    const monthTotals = sumBy(trades, monthOf)
    const symbols = [...symbolTotals.keys()].sort((a, b) => symbolTotals.get(b) - symbolTotals.get(a))
    return {
      symbols, cell, monthTotals, symbolTotals,
      maxAbs: Math.max(0, ...[...cell.values()].map(Math.abs)),
      grand: [...symbolTotals.values()].reduce((s, v) => s + v, 0),
    }
  }, [trades])
  const months = MONTH_NAMES.slice(0, lastMonth + 1)
  if (symbols.length === 0) return null
  return (
    <>
      <div className="report-table-wrap">
        <table className="report-table report-heat">
          <thead>
            <tr>
              <th>Symbol</th>
              {months.map((m) => <th key={m} className="num">{m}</th>)}
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {symbols.map((s) => (
              <tr key={s}>
                <td className="report-sym">{s}</td>
                {months.map((m, i) => {
                  const v = cell.get(`${s}|${i}`)
                  const step = pnlStep(v, maxAbs)
                  if (!step) return <td key={m} className="num report-heat-zero">—</td>
                  const label = `${s}, ${m}: ${signedUsd(v)}`
                  return (
                    <td
                      key={m}
                      className="num report-heat-cell"
                      style={step}
                      tabIndex={0}
                      title={label}
                      aria-label={label}
                      onClick={() => onCell(s, i)}
                      onKeyDown={keyActivate(() => onCell(s, i))}
                    >
                      {compactUsd(v)}
                    </td>
                  )
                })}
                <td className={`num report-heat-total ${signClass(symbolTotals.get(s))}`}>{compactUsd(symbolTotals.get(s))}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Month total</td>
              {months.map((m, i) => {
                const v = monthTotals.get(i)
                return (
                  <td key={m} className={`num report-row-link ${signClass(v)}`} tabIndex={v == null ? -1 : 0} onClick={() => v != null && onMonth(i)} onKeyDown={keyActivate(() => v != null && onMonth(i))}>
                    {v == null ? '—' : compactUsd(v)}
                  </td>
                )
              })}
              <td className={`num ${signClass(grand)}`}>{compactUsd(grand)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <HeatScale maxAbs={maxAbs} />
    </>
  )
}

/** Every weekday from Jan 1 to `endIso` as a small square, shaded by P&L. */
export function YearCalendar({ year, trades, endIso, onDay }) {
  const { cells, monthLabels, weeks, maxAbs } = useMemo(() => {
    const daily = sumBy(trades, (t) => t.close_date)
    const counts = countBy(trades, (t) => t.close_date)
    const start = mondayOf(`${year}-01-01`)
    const cells = [], monthLabels = []
    let week = 0, lastMonth = -1
    for (let mon = start; mon <= endIso; mon = addDays(mon, 7), week++) {
      for (let d = 0; d < 5; d++) {
        const date = addDays(mon, d)
        if (date.slice(0, 4) !== String(year) || date > endIso) continue
        const m = utcDate(date).getUTCMonth()
        if (m !== lastMonth) { lastMonth = m; monthLabels.push({ week, label: MONTH_NAMES[m] }) }
        cells.push({ date, week, d, value: daily.get(date), count: counts.get(date) ?? 0 })
      }
    }
    return { cells, monthLabels, weeks: week, maxAbs: Math.max(0, ...[...daily.values()].map(Math.abs)) }
  }, [year, trades, endIso])
  const size = 13, gap = 3, left = 30, top = 16
  const width = left + weeks * (size + gap)
  const height = top + 5 * (size + gap)
  return (
    <>
      <div className="report-ycal">
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="P&L for every trading day this year">
          {['Mon', 'Wed', 'Fri'].map((d, i) => (
            <text key={d} x={0} y={top + i * 2 * (size + gap) + size - 2} className="report-ycal-label">{d}</text>
          ))}
          {monthLabels.map((l) => (
            <text key={l.label} x={left + l.week * (size + gap)} y={10} className="report-ycal-label">{l.label}</text>
          ))}
          {cells.map((c) => {
            const step = pnlStep(c.value, maxAbs)
            const label = c.value == null ? `${longDate(c.date)}: no trades closed` : `${longDate(c.date)}: ${signedUsd(c.value)}, ${c.count} trade${c.count === 1 ? '' : 's'}`
            return (
              <rect
                key={c.date}
                x={left + c.week * (size + gap)}
                y={top + c.d * (size + gap)}
                width={size}
                height={size}
                rx={2}
                style={{ fill: step ? step.background : 'var(--pnl-neutral)' }}
                className="report-ycal-cell"
                tabIndex={0}
                aria-label={label}
                onClick={() => onDay(c.date)}
                onKeyDown={keyActivate(() => onDay(c.date))}
              >
                <title>{label}</title>
              </rect>
            )
          })}
        </svg>
      </div>
      <HeatScale maxAbs={maxAbs} />
    </>
  )
}

