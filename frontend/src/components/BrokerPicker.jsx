import { useEffect, useState } from 'react'
import { getBrokers, setBroker } from '../api/client'

/**
 * Which broker the Portfolio pages (Positions, Transactions, Reports) read,
 * saved per user on the server (api/portfolio/positions.py's /brokers and
 * /broker). Lists only the brokers the backend has registered
 * (service/portfolio/providers) — one today, so the choice is shown but
 * can't change yet. Switching brokers clears the chosen account, since
 * account numbers belong to one broker.
 *
 * Props:
 *   onChanged — called after a switch is saved, with the new list.
 */
export default function BrokerPicker({ onChanged }) {
  const [brokers, setBrokers] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    getBrokers()
      .then((list) => !cancelled && setBrokers(list))
      .catch((err) => !cancelled && setError(err.message || 'Could not load the brokers.'))
    return () => { cancelled = true }
  }, [])

  async function handleChange(e) {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const list = await setBroker(e.target.value)
      setBrokers(list)
      setSaved(true)
      onChanged?.(list)
    } catch (err) {
      setError(err.message || 'Could not switch brokers.')
    } finally {
      setSaving(false)
    }
  }

  if (!brokers) return error ? <div className="alert error">{error}</div> : null
  const selected = brokers.find((b) => b.selected)

  return (
    <div className="form-group">
      {error && <div className="alert error">{error}</div>}
      <label htmlFor="broker-picker">Broker</label>
      <select
        id="broker-picker"
        className="input"
        value={selected?.name ?? ''}
        onChange={handleChange}
        disabled={saving || brokers.length < 2}
      >
        {brokers.map((b) => <option key={b.name} value={b.name}>{b.label}</option>)}
      </select>
      <span className="summary-line">
        {saving
          ? 'Switching…'
          : saved
            ? `Saved — Positions, Transactions and Reports now read ${selected?.label}.`
            : brokers.length < 2
              ? `Positions, Transactions and Reports read ${selected?.label}. More brokers can be added later.`
              : `Positions, Transactions and Reports read ${selected?.label}.`}
      </span>
    </div>
  )
}
