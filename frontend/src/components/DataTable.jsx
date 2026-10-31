import { useEffect, useState } from 'react'

// Phones and tablets in portrait (tokens.css breakpoints): rows render as
// cards instead of a table that only shows three columns at a time.
export const PHONE_QUERY = '(max-width: 768px)'

function useMatchMedia(query) {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const media = window.matchMedia?.(query)
    if (!media) return
    const onChange = () => setMatches(media.matches)
    onChange()
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])
  return matches
}

// Where each column goes on a card. A label-less column with no data (a
// checkbox) leads the card unless `spec` places it. With `spec` ({ title, fields, hide }:
// column keys), the listed columns go there in the listed order and every
// other column goes under More; without it, the first column is the title,
// the next four are fields and the rest are under More.
function cardLayout(columns, sample, spec) {
  const placed = { control: [], title: [], field: [], more: [] }
  const rest = []
  const listed = new Set([...(spec?.title ?? []), ...(spec?.fields ?? [])])
  for (const col of columns) {
    if (!col.label && !(col.key in (sample ?? {})) && !listed.has(col.key)) placed.control.push(col)
    else if (!spec?.hide?.includes(col.key)) rest.push(col)
  }
  if (spec) {
    const byKey = Object.fromEntries(rest.map((c) => [c.key, c]))
    placed.title = (spec.title ?? []).map((k) => byKey[k]).filter(Boolean)
    placed.field = (spec.fields ?? []).map((k) => byKey[k]).filter(Boolean)
    const used = new Set([...placed.title, ...placed.field])
    placed.more = rest.filter((c) => !used.has(c))
  } else {
    placed.title = rest.slice(0, 1)
    placed.field = rest.slice(1, 5)
    placed.more = rest.slice(5)
  }
  return placed
}

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
 *   paginate        — split rows into pages (default true). The bar (row count +
 *                     rows-per-page) shows once a table has 10+ rows; page buttons
 *                     only when there's more than one page. Sorting applies to
 *                     all rows before paging. Rows-per-page is remembered per browser.
 *   cards           — on a phone (PHONE_QUERY) rows are cards; this places the columns, by
 *                     key: { title: [...] (the heading line — a second key sits at its
 *                     right end, e.g. P&L), fields: [...] (labelled values), hide: [...] }.
 *                     Every other column goes behind the card's More toggle. Without it,
 *                     the first column is the title and the next four are fields.
 *                     false keeps the table on a phone too — for a table already built
 *                     to fit one (a few short columns).
 *   defaultPageSize — rows per page until the user picks another size (default 25).
 *                     A table with its own default remembers its own choice, so
 *                     picking a size elsewhere doesn't override it.
 */
export default function DataTable({ data, columns: columnsProp, defaultSortKey, defaultSortDir = 'asc', maxHeight, paginate = true, defaultPageSize = DEFAULT_PAGE_SIZE, cards: cardSpec }) {
  const pageSizeKey = defaultPageSize === DEFAULT_PAGE_SIZE ? PAGE_SIZE_KEY : `${PAGE_SIZE_KEY}-${defaultPageSize}`
  const [sortCol, setSortCol] = useState(defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState(defaultSortDir)
  const [pageSize, setPageSize] = useState(() => loadPageSize(pageSizeKey, defaultPageSize))
  const [page, setPage] = useState(1)
  const asCards = useMatchMedia(PHONE_QUERY)
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
    try { localStorage.setItem(pageSizeKey, String(n)) } catch {}
  }

  const pagination = paginate && sorted.length >= PAGE_SIZES[0] && (
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
  )

  if (asCards && cardSpec !== false) {
    const layout = cardLayout(columns, data[0], cardSpec)
    const sortable = columns.filter(({ key, label }) => label && key != null && key in data[0])
    return (
      <>
        {sortable.length > 1 && (
          <div className="dt-sort">
            <label>
              Sort by
              <select value={sortCol ?? ''} onChange={(e) => { setSortCol(e.target.value || null); setSortDir('asc') }}>
                {sortCol == null && <option value="">As listed</option>}
                {sortable.map(({ key, label }) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            {sortCol != null && (
              <button
                type="button"
                className="dt-sort-dir"
                onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                aria-label={sortDir === 'asc' ? 'Sorted ascending — switch to descending' : 'Sorted descending — switch to ascending'}
              >
                {sortDir === 'asc' ? '↑' : '↓'}
              </button>
            )}
          </div>
        )}
        <ul className="dt-cards" style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
          {visible.map((row, i) => <Card key={start + i} row={row} layout={layout} />)}
        </ul>
        {pagination}
      </>
    )
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
    {pagination}
    </>
  )
}

function cellValue({ key, render }, row) {
  return render ? render(row) : fmt(row[key])
}

function Fields({ columns, row }) {
  return (
    <dl className="dt-card-fields">
      {columns.map((col) => (
        <div key={col.key}>
          <dt>{col.label}</dt>
          <dd className={col.render ? '' : getCellClass(col.key, row[col.key])}>{cellValue(col, row)}</dd>
        </div>
      ))}
    </dl>
  )
}

// One row as a card: control and title on the heading line (a second title
// column sits at its right end, e.g. P&L), fields beneath, the rest behind More.
function Card({ row, layout: { control, title, field, more } }) {
  const [main, ...aside] = title
  return (
    <li className="dt-card">
      {(control.length > 0 || main) && (
        <div className="dt-card-head">
          {control.map((col) => <span key={col.key} className="dt-card-control">{cellValue(col, row)}</span>)}
          {main && <span className="dt-card-title">{cellValue(main, row)}</span>}
          {aside.map((col) => (
            <span key={col.key} className={`dt-card-aside ${col.render ? '' : getCellClass(col.key, row[col.key])}`}>
              {cellValue(col, row)}
            </span>
          ))}
        </div>
      )}
      {field.length > 0 && <Fields columns={field} row={row} />}
      {more.length > 0 && (
        <details className="dt-card-more">
          <summary>More</summary>
          <Fields columns={more} row={row} />
        </details>
      )}
    </li>
  )
}

const PAGE_SIZES = [10, 25, 50, 100]
const DEFAULT_PAGE_SIZE = 25
const PAGE_SIZE_KEY = 'table-page-size'

// 0 means "All".
function loadPageSize(key, fallback) {
  try {
    const stored = localStorage.getItem(key)
    if (stored === null) return fallback
    const n = Number(stored)
    return n === 0 || PAGE_SIZES.includes(n) ? n : fallback
  } catch {
    return fallback
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
