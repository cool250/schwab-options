import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ResponsiveContainer, ComposedChart, AreaChart, Bar, Line, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, LabelList,
} from 'recharts'
import {
  MONTH_NAMES, tradeStats, openTradeStats, sumBy, countBy, runningTotal, pnlStep, symbolOf,
  utcDate, addDays, mondayOf, longDate, usd, signedUsd, compactUsd, pct, signClass,
} from '../utils/reportStats'

/*
 * The Reports page's views (pages/Reports.jsx): a key-numbers strip, a
 * month P&L calendar, a running total over daily bars, per-symbol tables,
 * and the YTD month grid / running total / symbol-by-month table /
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

/** Which trades a by-symbol table shows. */
export function SourceTabs({ value, onChange }) {
  return (
    <div className="tab-row report-source-tabs" role="tablist" aria-label="Trades to include">
      {[
        { id: 'options', label: 'Options' },
        { id: 'equity', label: 'Equity & futures' },
        { id: 'all', label: 'All' },
      ].map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          className={`tab-item ${value === t.id ? 'active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

/** Width of an element, kept current as it resizes. */
function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

// Charts fill their card's height (a chart card beside a taller one ends
// level with it) and never shrink below this.
const CHART_MIN_HEIGHT = 260

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
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// "$1,234" for an open-trade total — "…" while quotes load, a note when
// some legs couldn't be priced.
function openValueText(stats, loading) {
  if (stats.unrealized == null) return loading ? '…' : '—'
  return usd(stats.unrealized)
}

// Compact form for calendar cells: "$340", "…" while quotes load.
function openCompact(stats, loading) {
  if (stats.unrealized == null) return loading ? '…' : '—'
  return compactUsd(stats.unrealized)
}

/** Key numbers. `open` (Month view): { stats: openTradeStats(...), loading,
 *  monthName } — the still-open trades expiring in that month, shown as an
 *  Unrealized P&L column beside Option P&L (live prices), with their count. */
export function KpiStrip({ stats, prev, prevName, netNote, extraNet = 0, open = null }) {
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
    // Still-open trades expiring this month, beside the realized figure.
    open && {
      label: 'Unrealized P&L',
      value: <span className={signClass(open.stats.unrealized)}>{openValueText(open.stats, open.loading)}</span>,
      sub: (
        <>
          {plural(open.stats.n, 'open trade')} · expiring in {open.monthName}
          {open.stats.unpriced > 0 && open.stats.unrealized != null && (open.loading ? ' · pricing…' : ` · ${open.stats.unpriced} unpriced`)}
          <span className="report-kpi-subline" title="P&L if every open option expires worthless: shorts keep their premium, longs lose their cost">
            Max at expiry <span className={signClass(open.stats.atExpiry)}>{usd(open.stats.atExpiry)}</span>
          </span>
        </>
      ),
      hero: true,
    },
    {
      label: 'Trades',
      // Total, broken down as closed + expired + exercised.
      // Last month's total sits beside this month's, on the same line.
      value: (
        <>
          {stats.n.toLocaleString()}
          {prev && <>{' '}<span className="report-kpi-inline">{prev.n} in {prevName}</span></>}
        </>
      ),
      sub: (
        <>
          <span className="report-kpi-breakdown">
            <span title="Bought or sold back before expiration">{stats.closed} closed</span>
            <span title="Expired worthless">{stats.expired} expired</span>
            <span title={`Futures options exercised into their future (${signedUsd(stats.exercisedNet)} premium). Their premium is in Option P&L but not in win rate; the future's result is under Equity/futures.`}>
              {stats.exercised} exercised
            </span>
          </span>
        </>
      ),
      wide: true,
    },
    {
      label: 'Win rate',
      value: pct(stats.winRate),
      sub: prev ? `${pct(prev.winRate)} in ${prevName}` : stats.exercised ? 'excl. exercised' : '',
    },
    { label: 'Avg win', value: <span className="pnl-up">{usd(stats.avgWin)}</span>, sub: 'per winning trade' },
    { label: 'Avg loss', value: <span className="pnl-down">{usd(stats.avgLoss)}</span>, sub: 'per losing trade' },
    {
      label: 'Profit factor',
      value: stats.profitFactor == null ? '—' : stats.profitFactor.toFixed(2),
      sub: 'gross wins ÷ gross losses',
    },
  ].filter(Boolean)
  return (
    <div className="card">
      <div className={`report-kpis${open ? ' report-kpis--with-open' : ''}`}>
        {tiles.map((t) => (
          <div key={t.label} className={`report-kpi${t.hero ? ' report-kpi--hero' : ''}${t.wide ? ' report-kpi--wide' : ''}`}>
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
export function MonthCalendar({ year, month, trades, today, onDay, onWeek, openLegs = [], openLoading = false }) {
  const { weeks, maxAbs } = useMemo(() => {
    const daily = sumBy(trades, (t) => t.close_date)
    const counts = countBy(trades, (t) => t.close_date)
    // Still-open trades, on the day they expire (today or later).
    const openByDay = new Map()
    for (const leg of openLegs) {
      if (!openByDay.has(leg.expiration)) openByDay.set(leg.expiration, [])
      openByDay.get(leg.expiration).push(leg)
    }
    const first = `${year}-${String(month).padStart(2, '0')}-01`
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
    const last = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
    // Shade open days on the same scale as closed ones.
    const openValues = [...openByDay.entries()]
      .filter(([date]) => date >= first && date <= last)
      .map(([, legs]) => openTradeStats(legs).unrealized ?? 0)
    const out = []
    for (let mon = mondayOf(first); mon <= last; mon = addDays(mon, 7)) {
      const days = WEEKDAYS.map((_, i) => {
        const date = addDays(mon, i)
        const openLegsToday = date >= first && date <= last ? openByDay.get(date) ?? [] : []
        return {
          date, inMonth: date >= first && date <= last, future: date > today,
          value: daily.get(date), count: counts.get(date) ?? 0,
          open: openLegsToday.length ? openTradeStats(openLegsToday) : null,
        }
      })
      if (days.every((d) => !d.inMonth)) continue // a week of only weekend days of this month
      const traded = days.filter((d) => d.inMonth && d.value != null)
      const openLegsWeek = days.flatMap((d) => (d.inMonth ? openByDay.get(d.date) ?? [] : []))
      out.push({
        monday: mon, days, total: traded.reduce((s, d) => s + d.value, 0), tradedDays: traded.length,
        open: openLegsWeek.length ? openTradeStats(openLegsWeek) : null,
      })
    }
    return { weeks: out, maxAbs: Math.max(0, ...[...daily.values(), ...openValues].map(Math.abs)) }
  }, [year, month, trades, today, openLegs])

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
              // Open trades expiring this day: "2 open, unrealized +$340".
              const openLabel = d.open
                ? `${plural(d.open.n, 'open trade')} expiring, unrealized ${d.open.unrealized == null ? (openLoading ? 'loading' : 'unknown') : signedUsd(d.open.unrealized)}`
                : null
              if (d.future) {
                if (!d.open) {
                  return <div key={d.date} className="pnl-day pnl-day--future" role="gridcell"><span className="pnl-day-num">{dayNum}</span></div>
                }
                const label = `${longDate(d.date)}: ${openLabel}`
                const openStep = pnlStep(d.open.unrealized, maxAbs)
                return (
                  <button
                    key={d.date}
                    type="button"
                    role="gridcell"
                    className="pnl-day pnl-day--future pnl-day--open"
                    style={openStep ?? undefined}
                    title={label}
                    aria-label={label}
                    onClick={() => onDay(d.date, true)}
                  >
                    <span className="pnl-day-top">
                      <span className="pnl-day-num">{dayNum}</span>
                      <span className="pnl-day-count">{d.open.n} open</span>
                    </span>
                    <span className={`pnl-day-value${openStep ? '' : ` ${signClass(d.open.unrealized)}`}`}>
                      {openCompact(d.open, openLoading)}
                    </span>
                  </button>
                )
              }
              // Nothing closed but open trades expiring (e.g. today): show it
              // like a future open day — dashed, shaded by the unrealized P&L.
              const openOnly = d.value == null && d.open
              const step = openOnly ? pnlStep(d.open.unrealized, maxAbs) : pnlStep(d.value, maxAbs)
              const closedLabel = d.value == null
                ? `${longDate(d.date)}: no trades closed`
                : `${longDate(d.date)}: ${signedUsd(d.value)}, ${plural(d.count, 'trade')}`
              const label = openLabel ? `${closedLabel}; ${openLabel}` : closedLabel
              return (
                <button
                  key={d.date}
                  type="button"
                  role="gridcell"
                  className={`pnl-day${openOnly ? ' pnl-day--open' : d.value == null ? ' pnl-day--empty' : ''}`}
                  style={step ?? undefined}
                  title={label}
                  aria-label={label}
                  onClick={() => onDay(d.date, Boolean(d.open))}
                >
                  <span className="pnl-day-top">
                    <span className="pnl-day-num">{dayNum}</span>
                    {(d.count > 0 || d.open) && (
                      <span className="pnl-day-count">
                        {d.count > 0 && <>{d.count}<span className="pnl-full"> trade{d.count === 1 ? '' : 's'}</span></>}
                        {d.count > 0 && d.open && ' · '}
                        {d.open && `${d.open.n} open`}
                      </span>
                    )}
                  </span>
                  {openOnly ? (
                    <span className={`pnl-day-value${step ? '' : ` ${signClass(d.open.unrealized)}`}`}>
                      {openCompact(d.open, openLoading)}
                    </span>
                  ) : <span className="pnl-day-value">
                    {d.open && <span className="pnl-day-open" title="Unrealized, open trades expiring">{openCompact(d.open, openLoading)} open · </span>}
                    {d.value == null ? '—' : compactUsd(d.value)}
                  </span>}
                </button>
              )
            })}
            {w.tradedDays ? (
              <button
                type="button"
                role="gridcell"
                className="pnl-week"
                title={`Week of ${longDate(w.monday)}: ${signedUsd(w.total)}${w.open ? `; ${plural(w.open.n, 'open trade')} expiring, unrealized ${w.open.unrealized == null ? 'unknown' : signedUsd(w.open.unrealized)}` : ''}`}
                onClick={() => onWeek(w.monday, addDays(w.monday, 6), Boolean(w.open))}
              >
                <span className={`pnl-week-value ${signClass(w.total)}`}>
                  <span className="pnl-full">{signedUsd(w.total)}</span>
                  <span className="pnl-short">{w.total > 0 ? '+' : ''}{compactUsd(w.total)}</span>
                </span>
                <span className="pnl-week-days">{w.tradedDays} day{w.tradedDays === 1 ? '' : 's'}</span>
                {w.open && (
                  <span className={`pnl-week-open ${signClass(w.open.unrealized)}`}>
                    {w.open.unrealized > 0 ? '+' : ''}{openCompact(w.open, openLoading)} open
                  </span>
                )}
              </button>
            ) : w.open ? (
              // No trades closed yet this week, but some open ones expire in it.
              <button
                type="button"
                className="pnl-week pnl-week--open"
                role="gridcell"
                title={`Week of ${longDate(w.monday)}: ${plural(w.open.n, 'open trade')} expiring, unrealized ${w.open.unrealized == null ? 'unknown' : signedUsd(w.open.unrealized)}`}
                onClick={() => onWeek(w.monday, addDays(w.monday, 6), true)}
              >
                <span className={`pnl-week-value ${signClass(w.open.unrealized)}`}>
                  {w.open.unrealized == null ? (openLoading ? '…' : '—') : (
                    <>
                      <span className="pnl-full">{signedUsd(w.open.unrealized)}</span>
                      <span className="pnl-short">{w.open.unrealized > 0 ? '+' : ''}{compactUsd(w.open.unrealized)}</span>
                    </>
                  )}
                </span>
                <span className="pnl-week-days">{w.open.n} open</span>
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
    <ResponsiveContainer width="100%" height="100%" minHeight={CHART_MIN_HEIGHT}>
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
    (acc, r) => ({ n: acc.n + r.n, net: acc.net + r.net, wins: acc.wins + r.wins, decided: acc.decided + r.decided }),
    { n: 0, net: 0, wins: 0, decided: 0 }
  )
  const anyExercised = rows.some((r) => r.exercised)
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
                <td className="report-sym">
                  {r.symbol}
                  {r.exercised > 0 && (
                    <span
                      className="report-exercised"
                      title={`${r.exercised} exercised into the future (${signedUsd(r.exercisedNet)} premium). Counted in net P&L, not in win rate — the future's result is under Equity & futures.`}
                    >
                      {r.exercised} exercised
                    </span>
                  )}
                </td>
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
            <td className="num">{pct(total.decided ? total.wins / total.decided : null)}</td>
            <td className={`num ${signClass(total.net)}`}>{usd(total.n ? total.net / total.n : null)}</td>
            <td />
            <td className="num"><span className={`report-amt ${signClass(total.net)}`}>{usd(total.net)}</span></td>
          </tr>
        </tfoot>
      </table>
      {anyExercised && (
        <p className="report-footnote">
          Exercised: a futures option exercised into its future. Its premium is in net P&amp;L but left out of win
          rate; the future&apos;s own result is under Equity &amp; futures.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- YTD

/** Month-by-month grid for the year, laid out like MonthCalendar: one tile
 *  per month shaded by its P&L, three to a row, with the quarter's total at
 *  the end of each row. Months after lastMonth (0-based) haven't happened. */
export function MonthGrid({ trades, lastMonth, partialNote, onMonth, onQuarter }) {
  const { quarters, maxAbs } = useMemo(() => {
    const months = MONTH_NAMES.map((label, m) => {
      const st = tradeStats(trades.filter((t) => utcDate(t.close_date).getUTCMonth() === m))
      return { m, label, net: st.n ? st.net : null, n: st.n, winRate: st.winRate, future: m > lastMonth }
    })
    const quarters = [0, 1, 2, 3].map((q) => {
      const ms = months.slice(q * 3, q * 3 + 3)
      const traded = ms.filter((x) => x.net != null)
      return { q, months: ms, total: traded.reduce((s, x) => s + x.net, 0), tradedMonths: traded.length }
    })
    return { quarters, maxAbs: Math.max(0, ...months.map((x) => Math.abs(x.net ?? 0))) }
  }, [trades, lastMonth])

  return (
    <>
      <div className="pnl-cal pnl-cal--months" role="grid" aria-label="P&L by month">
        {quarters.map((qr) => (
          <div key={qr.q} className="pnl-cal-row" role="row">
            {qr.months.map((x) => {
              if (x.future) {
                return <div key={x.m} className="pnl-day pnl-day--future" role="gridcell"><span className="pnl-day-num">{x.label}</span></div>
              }
              const title = x.m === lastMonth && partialNote ? `${x.label} (${partialNote})` : x.label
              const label = x.net == null
                ? `${title}: no trades closed`
                : `${title}: ${signedUsd(x.net)}, ${plural(x.n, 'trade')}, win rate ${pct(x.winRate)}`
              return (
                <button
                  key={x.m}
                  type="button"
                  role="gridcell"
                  className={`pnl-day${x.net == null ? ' pnl-day--empty' : ''}`}
                  style={pnlStep(x.net, maxAbs) ?? undefined}
                  title={label}
                  aria-label={label}
                  onClick={() => onMonth(x.m)}
                >
                  <span className="pnl-day-top">
                    <span className="pnl-day-num">{x.label}</span>
                    {x.n > 0 && <span className="pnl-day-count">{x.n}<span className="pnl-full"> trade{x.n === 1 ? '' : 's'}</span></span>}
                  </span>
                  <span className="pnl-day-value">{x.net == null ? '—' : compactUsd(x.net)}</span>
                </button>
              )
            })}
            {qr.tradedMonths ? (
              <button
                type="button"
                role="gridcell"
                className="pnl-week"
                title={`Q${qr.q + 1}: ${signedUsd(qr.total)}`}
                onClick={() => onQuarter(qr.q)}
              >
                <span className={`pnl-week-value ${signClass(qr.total)}`}>
                  <span className="pnl-full">{signedUsd(qr.total)}</span>
                  <span className="pnl-short">{qr.total > 0 ? '+' : ''}{compactUsd(qr.total)}</span>
                </span>
                <span className="pnl-week-days">Q{qr.q + 1} · {qr.tradedMonths} mo</span>
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

/** Cumulative realized P&L across the year, one point per trading day. */
export function CumulativeChart({ trades, onDay }) {
  const data = useMemo(() => runningTotal(trades), [trades])
  const monthTicks = useMemo(() => {
    const seen = new Set()
    return data.filter((p) => { const m = p.date.slice(0, 7); if (seen.has(m)) return false; seen.add(m); return true }).map((p) => p.date)
  }, [data])
  if (data.length === 0) return null
  const EndLabel = endLabel(data.length, compactUsd)
  return (
    <ResponsiveContainer width="100%" height="100%" minHeight={CHART_MIN_HEIGHT}>
      <AreaChart
        data={data}
        margin={{ top: 20, right: 64, left: 0, bottom: 0 }}
        onClick={(s) => s?.activeLabel && onDay(s.activeLabel)}
        style={{ cursor: 'pointer' }}
      >
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
  // Squares sized so the year spans the card (between 9px and 22px; below
  // that the strip scrolls sideways instead of shrinking further).
  const [boxRef, boxWidth] = useWidth()
  const left = 30, top = 16, gap = 3
  const size = Math.max(9, Math.min(22, Math.floor((boxWidth - left) / Math.max(weeks, 1)) - gap))
  const width = left + weeks * (size + gap)
  const height = top + 5 * (size + gap)
  return (
    <>
      <div className="report-ycal" ref={boxRef}>
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

