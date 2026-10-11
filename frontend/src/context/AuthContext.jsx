import { createContext, useContext, useState } from 'react'

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
      }
    }
  } catch {}
  return token
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(initialToken)

  function login(t) {
    sessionStorage.setItem('auth_token', t)
    setToken(t)
  }

  function logout() {
    sessionStorage.removeItem('auth_token')
    setToken(null)
  }

  return (
    <AuthContext.Provider value={{ token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
