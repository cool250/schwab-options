import { useEffect, useRef } from 'react'
import DataTable from './DataTable'
import { money, count } from '../utils/numberFormat'
import { formatDate } from '../utils/dateFormat'
import { futuresRowPl } from '../utils/positionPl'

// On a phone the date stays fixed, the other columns scrolling beside it.
const DATE_PINNED = { pinned: 'date' }

/**
 * The open lots behind a futures position's average trade price — opened
 * from the Symbol link in Positions' Futures table. Each lot is one fill
 * still open (`lots` on the row, oldest first: the order FIFO closes them),
 * with its own trade price and P&L at the live price. Same dialog look as
 * the Strategy Builder (sb-* in strategy-builder.css): closes on ×, Escape,
 * or a click on the backdrop.
 */
export default function FuturesLotsDialog({ row, price, onClose }) {
  const closeRef = useRef(null)
  // The latest onClose, so the Escape listener and the focus move are set
  // up once per opening, not again on every parent render.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onCloseRef.current()
    document.addEventListener('keydown', onKey)
    closeRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const lots = row.lots ?? []
  const plOf = (lot) => futuresRowPl({ symbol: row.symbol, quantity: lot.quantity, trade_price: lot.trade_price }, price == null ? {} : { [row.symbol]: price })
  const total = futuresRowPl(row, price == null ? {} : { [row.symbol]: price })

  return (
    <div className="sb-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sb-dialog lots-dialog" role="dialog" aria-modal="true" aria-labelledby="lots-title">
        <div className="sb-top">
          <div className="sb-header">
            <div>
              <h2 className="sb-title" id="lots-title">/{row.symbol} trade prices</h2>
              <span className="text-muted">
                {count(row.quantity)} contracts · average {money(row.trade_price)}
                {price != null && ` · now ${money(price)}`}
              </span>
            </div>
            <button ref={closeRef} type="button" className="sb-close" onClick={onClose} aria-label="Close">×</button>
          </div>
        </div>
        <div className="sb-body">
          {lots.length ? (
            <>
              <DataTable
                data={lots}
                paginate={false}
                phone={DATE_PINNED}
                defaultSortKey="date"
                columns={[
                  { key: 'date', label: 'Opened', render: (lot) => formatDate(lot.date) },
                  { key: 'quantity', label: 'Qty', align: 'right', render: (lot) => count(lot.quantity) },
                  { key: 'trade_price', label: 'Price', align: 'right', render: (lot) => money(lot.trade_price) },
                  {
                    key: 'pl', label: 'P&L', align: 'right',
                    render: (lot) => {
                      const pl = plOf(lot)
                      return pl == null ? '—' : <span className={pl > 0 ? 'cell-positive' : pl < 0 ? 'cell-negative' : ''}>{money(pl)}</span>
                    },
                  },
                ]}
              />
              <p className="summary-line">
                Oldest first — the order they close in (first in, first out) when futures are sold or called away.
                {total != null && <> Total P&amp;L {money(total)}.</>}
              </p>
            </>
          ) : (
            <p className="summary-line">No lot detail for this position: its fills are older than the positions lookback.</p>
          )}
        </div>
      </div>
    </div>
  )
}
