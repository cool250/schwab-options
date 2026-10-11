import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTheme } from '../context/ThemeContext'
import { getSchwabStatus, startSchwabReconnect } from '../api/client'
import { stashTokenForRedirect, useAuth } from '../context/AuthContext'
import { AccountCard, UsersCard } from '../components/AccountSettings'

const THEMES = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

const DAY_MS = 24 * 3600 * 1000

function formatExpiry(iso) {
  return new Date(iso).toLocaleString('en-US', {
    month: '2-digit', day: '2-digit', year: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function statusLine(status) {
  if (!status.connected) return { tone: 'error', text: 'Not connected — connect Schwab to load positions and transactions.' }
  if (status.expired) return { tone: 'error', text: 'Expired — reconnect Schwab to keep positions and transactions loading.' }
  if (!status.refreshTokenExpiresAt) {
    return { tone: 'muted', text: 'Connected. Expiry unknown until you reconnect once through this page.' }
  }
  const msLeft = new Date(status.refreshTokenExpiresAt) - Date.now()
  const days = Math.floor(msLeft / DAY_MS)
  const hours = Math.floor((msLeft % DAY_MS) / 3600000)
  const left = days > 0 ? `${days}d ${hours}h` : `${hours}h`
  return {
    // Schwab's login lasts 7 days; flag the last day so it's renewed in time.
    tone: msLeft < DAY_MS ? 'warning' : 'ok',
    text: `Connected — expires ${formatExpiry(status.refreshTokenExpiresAt)} (in ${left}).`,
  }
}

export default function Settings() {
  const { theme, setTheme } = useTheme()
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [schwab, setSchwab] = useState(null)
  const [schwabError, setSchwabError] = useState(null)
  const [reconnecting, setReconnecting] = useState(false)
  // Result of a just-finished reconnect: the backend's callback redirects
  // here with ?schwab=connected|error&reason=… (api/auth.py). Captured once,
  // then the params are cleared so a refresh doesn't re-show it.
  const [result] = useState(() => ({
    outcome: searchParams.get('schwab'),
    reason: searchParams.get('reason'),
  }))

  useEffect(() => {
    if (result.outcome) setSearchParams({}, { replace: true })
    getSchwabStatus()
      .then(setSchwab)
      .catch((err) => setSchwabError(err.message || 'Could not load Schwab connection status.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleReconnect() {
    setReconnecting(true)
    setSchwabError(null)
    try {
      const { url } = await startSchwabReconnect()
      // Full-page navigation to Schwab's login; it redirects back to
      // /api/auth/schwab/callback, which lands on this page again — with
      // the app login handed off in case the browser drops sessionStorage
      // on the way (see AuthContext).
      stashTokenForRedirect()
      window.location.assign(url)
    } catch (err) {
      setSchwabError(err.message || 'Could not start the Schwab reconnect.')
      setReconnecting(false)
    }
  }

  const line = schwab && statusLine(schwab)

  return (
    <div className="page">
      {result.outcome === 'connected' && <div className="alert success">Schwab reconnected.</div>}
      {result.outcome === 'error' && (
        <div className="alert error">Schwab reconnect failed: {result.reason || 'unknown error'}</div>
      )}

      <AccountCard />

      <div className="card">
        <h3 className="section-title">Schwab Connection</h3>
        {/* Schwab's refresh token lasts 7 days and can only be renewed by
            logging in again — Reconnect runs that login here instead of via
            main.py + copying token.json to the server. */}
        {schwabError && <div className="alert error">{schwabError}</div>}
        {!schwab && !schwabError && <p className="summary-line">Checking connection…</p>}
        {line && <p className={`settings-status settings-status--${line.tone}`}>{line.text}</p>}
        <div>
          <button type="button" className="btn btn-primary" onClick={handleReconnect} disabled={reconnecting}>
            {reconnecting ? 'Opening Schwab…' : schwab?.connected ? 'Reconnect Schwab' : 'Connect Schwab'}
          </button>
        </div>
        <p className="summary-line">
          Schwab requires logging in again every 7 days. You'll be sent to Schwab to log in and approve access, then
          brought back here.
        </p>
      </div>

      <div className="card">
        <h3 className="section-title">Appearance</h3>
        {/* Applies immediately and is remembered on this browser
            (ThemeContext persists it to localStorage). */}
        <fieldset className="settings-field">
          <legend>Theme</legend>
          <div className="settings-options">
            {THEMES.map((t) => (
              <label key={t.value} className="toggle-label">
                <input
                  type="radio"
                  name="theme"
                  className="toggle-checkbox"
                  value={t.value}
                  checked={theme === t.value}
                  onChange={() => setTheme(t.value)}
                />
                <span>{t.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      {user?.isAdmin && <UsersCard />}
    </div>
  )
}
