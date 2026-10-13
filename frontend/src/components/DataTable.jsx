import { useEffect, useState } from 'react'

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
 *   columns         — optional array of { key, label, width?, align?, render? } for custom
 *                     headers; if omitted, columns are derived from Object.keys(data[0]).
 *                     `render(row)` overrides the default value formatting for that column
 *                     (e.g. a checkbox, or a formatted date/symbol) — it's still sortable by
 *                     `key` as long as `key` names a real field on the row data (sorting always
 *                     compares the raw row[key], never the rendered output); a column whose
 *                     `key` isn't a real field (e.g. a checkbox with no backing data) is not.
 *   defaultSortKey  — column key to sort by on first render
 *   maxHeight       — optional CSS max-height for the scroll container (e.g. "480px")
 *   paginate        — split rows into pages (default true); the controls only
 *                     appear when there's more than one page. Sorting applies to
 *                     all rows before paging. Rows-per-page is remembered per browser.
 */
export default function DataTable({ data, columns: columnsProp, defaultSortKey, defaultSortDir = 'asc', maxHeight, paginate = true }) {
  const [sortCol, setSortCol] = useState(defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState(defaultSortDir)
  const [pageSize, setPageSize] = useState(loadPageSize)
  const [page, setPage] = useState(1)
  const rowCount = data?.length ?? 0

  // Back to page 1 when the row count or the sort changes (a new search,
  // filter or re-sort) — but not on every new `data` array: several pages
  // rebuild their rows on each live-quote refresh, which would otherwise
  // keep yanking the user back to page 1.
  useEffect(() => { setPage(1) }, [rowCount, sortCol, sortDir, pageSize])

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
        // Real numbers compare numerically — a numeric-collation string
        // compare ignores the minus sign, so e.g. put deltas (-0.45, -0.30)
        // would sort as if positive.
        const cmp = typeof av === 'number' && typeof bv === 'number'
          ? av - bv
          : String(av).localeCompare(String(bv), undefined, { numeric: true })
        return sortDir === 'asc' ? cmp : -cmp
      })
    : data

  const size = paginate && pageSize > 0 ? pageSize : sorted.length
  const pageCount = Math.max(1, Math.ceil(sorted.length / size))
  const current = Math.min(page, pageCount)
  const start = (current - 1) * size
  const visible = sorted.slice(start, start + size)

  function changePageSize(n) {
    setPageSize(n)
    try { localStorage.setItem(PAGE_SIZE_KEY, String(n)) } catch {}
  }

  return (
    <>
    <div className="table-scroll" style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map(({ key, label, width, align, render }) => {
              const isNumeric = align === 'right' || typeof data[0]?.[key] === 'number'
              // A render column (e.g. a formatted date, or a checkbox) is
              // still sortable by its raw row[key] as long as key names a
              // real field on the row — only a key with no backing data
              // (like a checkbox column) is excluded.
              const sortable = key != null && data[0] != null && key in data[0]
              return (
                <th
                  key={key}
                  onClick={sortable ? () => toggleSort(key) : undefined}
                  className={sortable ? 'th-sortable' : ''}
                  style={{ width, textAlign: align ?? (isNumeric ? 'right' : 'left') }}
                >
                  {label}
                  {sortable && sortCol === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, i) => (
            <tr key={start + i}>
              {columns.map(({ key, align, render }) => {
                const val = row[key]
                const isNumeric = align === 'right' || typeof val === 'number'
                return (
                  <td
                    key={key}
                    className={render ? '' : getCellClass(key, val)}
                    style={{ textAlign: align ?? (isNumeric ? 'right' : 'left') }}
                  >
                    {render ? render(row) : fmt(val)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {paginate && sorted.length > PAGE_SIZES[0] && (
      <Pagination
        page={current}
        pageCount={pageCount}
        start={start}
        shown={visible.length}
        total={sorted.length}
        pageSize={pageSize}
        onPage={setPage}
        onPageSize={changePageSize}
      />
    )}
    </>
  )
}

const PAGE_SIZES = [10, 25, 50, 100]
const DEFAULT_PAGE_SIZE = 25
const PAGE_SIZE_KEY = 'table-page-size'

// 0 means "All".
function loadPageSize() {
  try {
    const n = Number(localStorage.getItem(PAGE_SIZE_KEY))
    if (n === 0 && localStorage.getItem(PAGE_SIZE_KEY) !== null) return 0
    return PAGE_SIZES.includes(n) ? n : DEFAULT_PAGE_SIZE
  } catch {
    return DEFAULT_PAGE_SIZE
  }
}

// Page numbers to show: first, last, and up to two either side of the
// current page, with gaps marked by null ("…").
function pageWindow(page, pageCount) {
  const pages = []
  for (let p = 1; p <= pageCount; p++) {
    if (p === 1 || p === pageCount || Math.abs(p - page) <= 2) pages.push(p)
    else if (pages[pages.length - 1] !== null) pages.push(null)
  }
  return pages
}

function Pagination({ page, pageCount, start, shown, total, pageSize, onPage, onPageSize }) {
  return (
    <div className="table-pagination">
      <span className="table-pagination-summary">
        Showing {start + 1}–{start + shown} of {total.toLocaleString('en-US')}
      </span>
      <label className="table-pagination-size">
        Rows
        <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} aria-label="Rows per page">
          {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          <option value={0}>All</option>
        </select>
      </label>
      {pageCount > 1 && (
        <nav className="table-pagination-pages" aria-label="Table pages">
          <button type="button" onClick={() => onPage(1)} disabled={page === 1} aria-label="First page">«</button>
          <button type="button" onClick={() => onPage(page - 1)} disabled={page === 1} aria-label="Previous page">‹</button>
          {pageWindow(page, pageCount).map((p, i) => (p === null
            ? <span key={`gap${i}`} className="table-pagination-gap">…</span>
            : (
              <button
                key={p}
                type="button"
                className={p === page ? 'active' : ''}
                aria-current={p === page ? 'page' : undefined}
                onClick={() => onPage(p)}
              >
                {p}
              </button>
            )))}
          <button type="button" onClick={() => onPage(page + 1)} disabled={page === pageCount} aria-label="Next page">›</button>
          <button type="button" onClick={() => onPage(pageCount)} disabled={page === pageCount} aria-label="Last page">»</button>
        </nav>
      )}
    </div>
  )
}
