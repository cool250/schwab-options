import { useEffect, useState } from 'react'
import { getAccounts, setAccount } from '../api/client'

const compactUsd = (v) =>
  v == null ? '' : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`

function optionLabel(a) {
  const type = a.type ? a.type.charAt(0) + a.type.slice(1).toLowerCase() : null
  return [a.label, type, compactUsd(a.value), `${a.positions} position${a.positions === 1 ? '' : 's'}`]
    .filter(Boolean)
    .join(' · ')
}

/**
 * Which broker account the Portfolio pages (Positions, Transactions,
 * Reports) read, when the user's broker login covers more than one. The
 * choice is saved per user on the server (api/portfolio/positions.py's /accounts and
 * /account), so it applies on every page and device.
 *
 * Props:
 *   inline      — compact one-row layout (above every Portfolio page, via RequireSchwab) instead of the
 *                 Settings form field; also hides itself entirely when the
 *                 login covers a single account, or the list can't load.
 *   onChanged   — called after a switch is saved, so a page can reload.
 */
export default function AccountPicker({ inline = false, onChanged }) {
  const [accounts, setAccounts] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    getAccounts()
      .then((list) => !cancelled && setAccounts(list))
      .catch((err) => !cancelled && setError(err.message || 'Could not load your accounts.'))
    return () => { cancelled = true }
  }, [])

  async function handleChange(e) {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const list = await setAccount(e.target.value)
      setAccounts(list)
      setSaved(true)
      onChanged?.(list)
    } catch (err) {
      setError(err.message || 'Could not switch accounts.')
    } finally {
      setSaving(false)
    }
  }

  if (inline && (!accounts || accounts.length < 2)) return null
  if (!accounts) return error ? <div className="alert error">{error}</div> : null

  const selected = accounts.find((a) => a.selected)
  const select = (
    <select
      id={inline ? 'account-picker-inline' : 'account-picker'}
      className="input"
      value={selected?.id ?? ''}
      onChange={handleChange}
      disabled={saving || accounts.length < 2}
    >
      {/* The Portfolio pages (inline) show just the masked account number; Settings
          adds type, value and position count to help tell accounts apart. */}
      {accounts.map((a) => <option key={a.id} value={a.id}>{inline ? a.label : optionLabel(a)}</option>)}
    </select>
  )

  if (inline) {
    return (
      <div className="account-picker-inline">
        <label htmlFor="account-picker-inline">Account</label>
        {select}
        {saving && <span className="summary-line">Switching…</span>}
        {error && <span className="summary-line account-picker-error">{error}</span>}
      </div>
    )
  }

  return (
    <div className="form-group account-picker">
      {error && <div className="alert error">{error}</div>}
      <label htmlFor="account-picker">Account</label>
      {select}
      <span className="summary-line">
        {saving
          ? 'Switching…'
          : saved
            ? `Saved — Positions, Transactions and Reports now show ${selected?.label}.`
            : accounts.length < 2
              ? 'Your login covers this one account.'
              : 'Positions, Transactions and Reports show this account.'}
      </span>
    </div>
  )
}
