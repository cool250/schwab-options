import { useState } from 'react'

function fmt(val) {
  if (val == null) return '—'
  if (typeof val === 'number') return val.toLocaleString('en-US', { maximumFractionDigits: 2 })
  return String(val)
}

const PL_KEYS = ['total', 'gain', 'return', 'pl', 'profit', 'loss', 'amount']

function getCellClass(key, val) {
  if (typeof val !== 'number') return ''
  const lk = key.toLowerCase()
  if (PL_KEYS.some((k) => lk.includes(k))) {
    if (val > 0) return 'cell-positive'
    if (val < 0) return 'cell-negative'
  }
  return ''
}

/**
 * Shared table component used across all pages.
 *
 * Props:
 *   data            — array of row objects (required)
 *   columns         — optional array of { key, label, width?, align? } for custom headers;
 *                     if omitted, columns are derived from Object.keys(data[0])
 *   defaultSortKey  — column key to sort by on first render
 *   maxHeight       — optional CSS max-height for the scroll container (e.g. "480px")
 */
export default function DataTable({ data, columns: columnsProp, defaultSortKey, maxHeight }) {
  const [sortCol, setSortCol] = useState(defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState('asc')

  if (!data || data.length === 0) return null

  const columns = columnsProp
    ? columnsProp
    : Object.keys(data[0]).map((k) => ({ key: k, label: k.replace(/_/g, ' ') }))

  function toggleSort(key) {
    if (sortCol === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(key)
      setSortDir('asc')
    }
  }

  const sorted = sortCol
    ? [...data].sort((a, b) => {
        const av = a[sortCol] ?? ''
        const bv = b[sortCol] ?? ''
        const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
        return sortDir === 'asc' ? cmp : -cmp
      })
    : data

  return (
    <div className="table-scroll" style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map(({ key, label, width, align }) => {
              const isNumeric = align === 'right' || typeof data[0]?.[key] === 'number'
              return (
                <th
                  key={key}
                  onClick={() => toggleSort(key)}
                  className="th-sortable"
                  style={{ width, textAlign: align ?? (isNumeric ? 'right' : 'left') }}
                >
                  {label}
                  {sortCol === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i}>
              {columns.map(({ key, align }) => {
                const val = row[key]
                const isNumeric = align === 'right' || typeof val === 'number'
                return (
                  <td
                    key={key}
                    className={getCellClass(key, val)}
                    style={{ textAlign: align ?? (isNumeric ? 'right' : 'left') }}
                  >
                    {fmt(val)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
