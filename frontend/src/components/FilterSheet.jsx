import { useEffect, useState } from 'react'
import { PHONE_QUERY, useMatchMedia } from './DataTable'

/**
 * A search form's card that folds away on a phone once there are results.
 * The form then sits behind a "Filters" bar (with a one-line summary of
 * what's set) and opens as a sheet sliding up from the bottom; running the
 * search closes it again. Before the first results, and always on a wider
 * screen, it's the plain card.
 *
 * The form stays mounted while folded (only hidden), so nothing in it
 * resets.
 *
 * Props:
 *   folded   — whether there are results to fold the form above
 *   summary  — what's set, e.g. "AAPL · 0–7 DTE"
 *   children — the <form>
 */
export default function FilterSheet({ folded, summary, children }) {
  const phone = useMatchMedia(PHONE_QUERY)
  const [open, setOpen] = useState(false)
  const sheet = phone && folded

  useEffect(() => {
    if (!sheet || !open) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [sheet, open])

  if (!sheet) return <div className="card">{children}</div>

  return (
    <>
      <button type="button" className="filter-bar" onClick={() => setOpen(true)} aria-expanded={open}>
        <span className="filter-bar-label">Filters</span>
        {summary && <span className="filter-bar-summary">{summary}</span>}
        <span className="filter-bar-edit" aria-hidden="true">Edit</span>
      </button>
      {open && <div className="filter-sheet-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}
      <div
        className={`card filter-sheet${open ? ' open' : ''}`}
        role="dialog"
        aria-label="Filters"
        onSubmit={() => setOpen(false)}
      >
        <div className="filter-sheet-head">
          <h3 className="section-title">Filters</h3>
          <button type="button" className="btn btn-secondary" onClick={() => setOpen(false)}>Close</button>
        </div>
        {children}
      </div>
    </>
  )
}
