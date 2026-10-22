import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSchwabStatus } from '../api/client'
import { beginSchwabConnect } from '../utils/schwabConnect'
import AccountPicker from './AccountPicker'
import { PortfolioIcon } from './NavIcons'
import Spinner from './Spinner'

/** Gate for the Portfolio pages (Positions, Transactions, Reports), which
 *  read the current user's own Schwab account. Checks the connection first
 *  and, if it's missing or expired, explains that and offers to connect —
 *  instead of letting the page fire its data requests and show a red
 *  "Broker authentication failed" error. If the status check itself fails,
 *  the page renders anyway and handles errors as before.
 *
 *  Once connected, it also puts the account picker above every Portfolio
 *  page (only shown when the login covers more than one account). A switch
 *  remounts the page, so everything it loaded for the old account is
 *  dropped and fetched again for the new one. */
export default function RequireSchwab({ children }) {
  const [state, setState] = useState('checking') // 'checking' | 'ok' | 'missing' | 'expired'
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState(null)
  const [accountVersion, setAccountVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    getSchwabStatus()
      .then((s) => {
        if (cancelled) return
        setState(!s.connected ? 'missing' : s.expired ? 'expired' : 'ok')
      })
      .catch(() => { if (!cancelled) setState('ok') })
    return () => { cancelled = true }
  }, [])

  async function handleConnect() {
    setConnecting(true)
    setError(null)
    try {
      await beginSchwabConnect()
    } catch (err) {
      setError(err.message || 'Could not start the Schwab connection.')
      setConnecting(false)
    }
  }

  if (state === 'checking') return <Spinner />
  if (state === 'ok') {
    return (
      <>
        <div className="portfolio-account-bar">
          <AccountPicker inline onChanged={() => setAccountVersion((v) => v + 1)} />
        </div>
        <Fragment key={accountVersion}>{children}</Fragment>
      </>
    )
  }

  const expired = state === 'expired'
  return (
    <div className="page">
      <div className="card connect-notice">
        <span className="connect-notice-icon" aria-hidden="true"><PortfolioIcon /></span>
        <h2 className="connect-notice-title">
          {expired ? 'Your Schwab connection has expired' : 'Connect your Schwab account'}
        </h2>
        <p className="connect-notice-text">
          {expired
            ? 'Schwab requires logging in again every 7 days. Reconnect to keep your positions, transactions and reports up to date.'
            : 'Positions, Transactions and Reports come from your own Schwab account. Connect it once from Settings to see them here.'}
        </p>
        <p className="connect-notice-text connect-notice-text--muted">
          NuTrade only reads your account — it never places, changes or cancels orders. Analyze, Charts and Screener
          work without a Schwab connection.
        </p>
        {error && <div className="alert error">{error}</div>}
        <div className="connect-notice-actions">
          <button type="button" className="btn btn-primary" onClick={handleConnect} disabled={connecting}>
            {connecting ? 'Opening Schwab…' : expired ? 'Reconnect Schwab' : 'Connect Schwab'}
          </button>
          <Link to="/settings" className="btn btn-secondary">Open Settings</Link>
        </div>
      </div>
    </div>
  )
}
