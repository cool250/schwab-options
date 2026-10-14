import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { getMe, refreshSession } from '../api/client'
import { clearSessionCaches } from '../utils/sessionCaches'

const AuthContext = createContext(null)

// The app login lives in sessionStorage (per tab, gone when the tab closes).
// A full-page round trip through Schwab's login (Settings → Reconnect
// Schwab) can come back in a fresh browsing context — login/banking sites
// commonly set headers that make the browser swap contexts — which loses
// sessionStorage and drops the user on /login. So right before leaving,
// the token is handed off via localStorage and restored (then deleted) on
// return. Only honored for a short window so a stale hand-off is useless.
const HANDOFF_KEY = 'auth_token_handoff'
const HANDOFF_TTL_MS = 15 * 60 * 1000

export function stashTokenForRedirect() {
  try {
    const token = sessionStorage.getItem('auth_token')
    if (token) localStorage.setItem(HANDOFF_KEY, JSON.stringify({ token, at: Date.now() }))
  } catch {}
}

function initialToken() {
  let token = null
  try {
    token = sessionStorage.getItem('auth_token')
    const raw = localStorage.getItem(HANDOFF_KEY)
    if (raw) {
      localStorage.removeItem(HANDOFF_KEY) // one-shot, whether used or not
      const handoff = JSON.parse(raw)
      if (!token && handoff?.token && Date.now() - handoff.at < HANDOFF_TTL_MS) {
        token = handoff.token
        sessionStorage.setItem('auth_token', token)
        sessionStorage.setItem(ISSUED_KEY, String(handoff.at))
      }
    }
  } catch {}
  return token
}

// Sessions end after 15 minutes of inactivity (api/auth.py: tokens live 15
// minutes). While the user is active, the token is renewed once it's 5
// minutes old; only real input counts as activity — background polling and
// the Analyze live stream don't, so an idle tab signs out (which also
// closes its stream, letting the Fly machine auto-stop).
const IDLE_LIMIT_MS = 15 * 60 * 1000
const RENEW_AFTER_MS = 5 * 60 * 1000
const ISSUED_KEY = 'auth_token_issued'
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll']

function tokenIssuedAt() {
  try {
    return Number(sessionStorage.getItem(ISSUED_KEY)) || 0
  } catch {
    return 0
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(initialToken)
  // {id, username, isAdmin} — from the login response, or fetched via
  // /auth/me when a session is restored (page reload, Schwab round trip).
  const [user, setUser] = useState(null)

  useEffect(() => {
    if (!token || user) return
    let cancelled = false
    getMe()
      .then((me) => { if (!cancelled) setUser(me) })
      .catch(() => {}) // a 401 is handled by request() (→ /login)
    return () => { cancelled = true }
  }, [token, user])

  function login(t, u = null) {
    // A new login may be a different user: drop every page's cached data
    // first (see utils/sessionCaches.js). Skipped for a token refresh of the
    // same session (renewSession doesn't go through here).
    if (t !== token) clearSessionCaches()
    sessionStorage.setItem('auth_token', t)
    sessionStorage.setItem(ISSUED_KEY, String(Date.now()))
    setToken(t)
    setUser(u ?? user)
  }

  // Refresh the signed-in user's details (e.g. after editing their profile)
  // without touching the token or its renewal timing.
  function updateUser(u) {
    setUser(u)
  }

  function logout() {
    clearSessionCaches()
    sessionStorage.removeItem('auth_token')
    sessionStorage.removeItem(ISSUED_KEY)
    setToken(null)
    setUser(null)
  }

  // Renew the token now (used before leaving for Schwab's login, so the
  // hand-off token has the full 15 minutes).
  async function renewSession() {
    const { token: fresh } = await refreshSession()
    sessionStorage.setItem('auth_token', fresh)
    sessionStorage.setItem(ISSUED_KEY, String(Date.now()))
    setToken(fresh)
    return fresh
  }

  const renewing = useRef(false)
  useEffect(() => {
    if (!token) return
    let lastActivity = Date.now()

    async function check() {
      const now = Date.now()
      if (now - lastActivity >= IDLE_LIMIT_MS) {
        sessionStorage.setItem('auth_notice', 'You were signed out after 15 minutes of inactivity.')
        logout()
        return
      }
      // Active recently and the token is getting old: renew it.
      if (now - tokenIssuedAt() >= RENEW_AFTER_MS && !renewing.current) {
        renewing.current = true
        try {
          await renewSession()
        } catch {
          // A 401 here is handled by request() (→ /login); anything else
          // (network blip) just retries on the next check.
        } finally {
          renewing.current = false
        }
      }
    }

    const onActivity = () => {
      const wasIdleFor = Date.now() - lastActivity
      lastActivity = Date.now()
      // Coming back after a while: renew right away rather than waiting for
      // the next tick, so the click that woke us doesn't hit an expired token.
      if (wasIdleFor > 30_000) check()
    }
    // Background tabs throttle timers; re-check as soon as the tab is shown.
    const onVisible = () => { if (document.visibilityState === 'visible') check() }

    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, onActivity, { passive: true }))
    document.addEventListener('visibilitychange', onVisible)
    const timer = setInterval(check, 30_000)
    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, onActivity))
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  return (
    <AuthContext.Provider value={{ token, user, login, logout, renewSession, updateUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
