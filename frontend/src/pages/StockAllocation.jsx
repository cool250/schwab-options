import { useState } from 'react'
import {
  PieChart, Pie, Cell, Tooltip as PieTooltip, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as BarTooltip, Legend as BarLegend, ResponsiveContainer,
} from 'recharts'
import { getMonthlyAllocations } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const COLORS = [
  '#1a56db', '#059669', '#d97706', '#dc2626', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#ea580c', '#0284c7',
]

function monthName(m) {
  return new Date(2000, m - 1, 1).toLocaleString('en-US', { month: 'long' })
}

function currentYear() { return new Date().getFullYear() }
function currentMonth() { return new Date().getMonth() + 1 }

// Group rows by ISO week number
function isoWeek(dateStr) {
  const d = new Date(dateStr)
  const jan4 = new Date(d.getFullYear(), 0, 4)
  const startOfWeek1 = new Date(jan4)
  startOfWeek1.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7))
  const diff = d - startOfWeek1
  return Math.floor(diff / (7 * 24 * 3600 * 1000)) + 1
}

export default function StockAllocation() {
  const [year, setYear] = useState(currentYear)
  const [month, setMonth] = useState(currentMonth)
  const [realizedOnly, setRealizedOnly] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [submitted, setSubmitted] = useState(false)
  const [pieData, setPieData] = useState([])
  const [weeklyData, setWeeklyData] = useState([])
  const [tableData, setTableData] = useState([])
  const [total, setTotal] = useState(0)
  const [label, setLabel] = useState('')

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear() - i)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setSubmitted(false)
    try {
      const data = await getMonthlyAllocations(year, month, realizedOnly)
      if (!data || data.length === 0) {
        setPieData([]); setWeeklyData([]); setTableData([]); setTotal(0)
        setSubmitted(true)
        return
      }

      // Aggregate by underlying_symbol
      const bySymbol = {}
      for (const row of data) {
        const sym = row.underlying_symbol ?? row.symbol ?? 'OTHER'
        bySymbol[sym] = (bySymbol[sym] ?? 0) + (row.total_amount ?? 0)
      }
      const agg = Object.entries(bySymbol)
        .filter(([, v]) => v !== 0)
        .map(([name, value]) => ({ name, value }))
      const tot = agg.reduce((s, r) => s + r.value, 0)
      setPieData(agg)
      setTotal(tot)
      setTableData(agg.map((r) => ({ symbol: r.name, amount: r.value, percent: (r.value / tot) * 100 })))
      setLabel(`${monthName(month)} ${year}`)

      // Weekly grouped bar chart
      const weekMap = {} // { week: { sym: amount } }
      for (const row of data) {
        if (!row.date) continue
        const week = `W${isoWeek(row.date)}`
        const sym = row.underlying_symbol ?? row.symbol ?? 'OTHER'
        if (!weekMap[week]) weekMap[week] = {}
        weekMap[week][sym] = (weekMap[week][sym] ?? 0) + (row.total_amount ?? 0)
      }
      const allSymbols = [...new Set(data.map((r) => r.underlying_symbol ?? r.symbol ?? 'OTHER'))]
      const weekly = Object.entries(weekMap)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([week, syms]) => ({ week, ...syms }))
      setWeeklyData({ rows: weekly, symbols: allSymbols })
      setSubmitted(true)
    } catch {
      setError('Failed to fetch allocation data. Make sure the API server is running.')
    } finally {
      setLoading(false)
    }
  }

  const noData = submitted && pieData.length === 0

  return (
    <div className="page">
      <h2 className="page-title">Monthly Gains</h2>

      <div className="card">
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label>Year</label>
              <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="input">
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Month</label>
              <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="input">
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <option key={m} value={m}>{monthName(m)}</option>
                ))}
              </select>
            </div>
            <div className="form-group" style={{ justifyContent: 'flex-end' }}>
              <label style={{ visibility: 'hidden' }}>_</label>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={realizedOnly}
                  onChange={(e) => setRealizedOnly(e.target.checked)}
                  className="toggle-checkbox"
                />
                <span>Realized Gains Only</span>
              </label>
            </div>
            <div className="form-group" style={{ justifyContent: 'flex-end' }}>
              <label style={{ visibility: 'hidden' }}>_</label>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                Submit
              </button>
            </div>
          </div>
        </form>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {noData && !loading && (
        <div className="alert warning">No transaction data available for this month.</div>
      )}

      {submitted && !loading && pieData.length > 0 && (
        <>
          <div className="charts-row">
            {/* Pie chart */}
            <div className="card chart-card">
              <h3 className="section-title">
                Stock Allocation — {label}
                <span className="chart-total"> (${total.toLocaleString('en-US', { minimumFractionDigits: 2 })})</span>
              </h3>
              <ResponsiveContainer width="100%" height={320}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={110}
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(1)}%`}
                    labelLine={false}
                  >
                    {pieData.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <PieTooltip formatter={(v) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2 })}`} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>

            {/* Weekly bar chart */}
            {weeklyData.rows?.length > 0 && (
              <div className="card chart-card">
                <h3 className="section-title">Weekly Allocation — {label}</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={weeklyData.rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="week" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
                    <BarTooltip formatter={(v) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2 })}`} />
                    <BarLegend />
                    {weeklyData.symbols.map((sym, i) => (
                      <Bar key={sym} dataKey={sym} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Summary table */}
          <div className="card">
            <h3 className="section-title">Summary</h3>
            <DataTable
              data={tableData}
              columns={[
                { key: 'symbol', label: 'Symbol' },
                { key: 'amount', label: 'Amount ($)' },
                { key: 'percent', label: 'Percent (%)' },
              ]}
              defaultSortKey="amount"
            />
          </div>
        </>
      )}
    </div>
  )
}
