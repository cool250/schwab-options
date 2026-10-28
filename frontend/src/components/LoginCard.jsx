import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

/** The login form card — shown as an overlay on the landing page (both from
 *  its "Log in" button and at /login). Always dark (see login.css), since
 *  it hosts the light-text logo. */
export function LoginCard({ onSuccess, onClose }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  // Set when the session ended (idle sign-out, or a 401) — shown once.
  const [notice] = useState(() => {
    try {
      const n = sessionStorage.getItem('auth_notice')
      sessionStorage.removeItem('auth_notice')
      return n
    } catch {
      return null
    }
  })

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (res.status === 429) {
        // api/login_limits.py: logins paused after repeated failures.
        const minutes = Math.max(1, Math.ceil(Number(res.headers.get('Retry-After')) / 60) || 15)
        setError(`Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`)
        return
      }
      if (!res.ok) {
        setError('Invalid username or password.')
        return
      }
      const { token, user } = await res.json()
      login(token, user)
      onSuccess?.()
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-card">
      {onClose && (
        <button type="button" className="login-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      )}
      <div className="login-header">
        <img src="/indutrades_logo.svg" alt="InduTrades" className="login-logo" />
        <p className="login-subtitle" id="login-title">Sign in to continue</p>
      </div>

      {notice && <div className="alert warning">{notice}</div>}

      <form onSubmit={handleSubmit} className="login-form">
        <div className="form-group">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input"
            autoComplete="username"
            autoFocus
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
            autoComplete="current-password"
            required
          />
        </div>

        {error && <div className="alert error">{error}</div>}

        <button type="submit" className="btn btn-primary login-btn" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
