import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import CopilotWidget, { CopilotDisabledLauncher } from './components/CopilotWidget'
import RequireSchwab from './components/RequireSchwab'
import TouchTitles from './components/TouchTitles'
import Spinner from './components/Spinner'
import Login from './pages/Login'
import Landing from './pages/Landing'
import Home from './pages/Home'
import Positions from './pages/Positions'
import Transactions from './pages/Transactions'
import Screener from './pages/Screener'
import Settings from './pages/Settings'

// The pages that draw charts load on first visit, with the chart library
// (its own ~400 KB chunk, vite.config.js) — so it isn't downloaded for the
// pages that don't need it.
// A tab opened before a deploy asks for chunk names that no longer exist:
// reload once to pick up the new build instead of showing an error.
const lazyPage = (load) => lazy(() => load().then(
  (page) => { try { sessionStorage.removeItem('chunk-reload') } catch {} return page },
  (err) => {
    let reloaded = true
    try {
      reloaded = sessionStorage.getItem('chunk-reload') === '1'
      sessionStorage.setItem('chunk-reload', '1')
    } catch {}
    if (reloaded) throw err
    window.location.reload()
    return new Promise(() => {})
  },
))
const Reports = lazyPage(() => import('./pages/Reports'))
const StrikeLab = lazyPage(() => import('./pages/StrikeLab'))
const Charts = lazyPage(() => import('./pages/Charts'))

// The Copilot is admin-only (it's billed to the admin's OpenAI key; the API
// enforces this too — api/app.py mounts it behind require_admin). Everyone
// else sees its launcher greyed out, so the feature isn't a mystery.
function AdminCopilot() {
  const { user } = useAuth()
  if (!user) return null
  return user.isAdmin ? <CopilotWidget /> : <CopilotDisabledLauncher />
}

export default function App() {
  return (
    <ThemeProvider>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public: landing page (Log in / Register open as overlays on it);
              /login is the same page with the login overlay already open. */}
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                {/* app-shell reserves room for the fixed sidebar navbar on
                    desktop (see navbar.css) — the same way body.copilot-open
                    reserves room for the docked Copilot panel on the right. */}
                <div className="app-shell">
                  <Navbar />
                  <main className="main-content">
                    <ErrorBoundary>
                      <Suspense fallback={<Spinner />}>
                      <Routes>
                        {/* Portfolio pages read the user's own Schwab account —
                            RequireSchwab shows a "connect Schwab" notice first
                            if it isn't connected or has expired. */}
                        <Route path="/home" element={<RequireSchwab><Home /></RequireSchwab>} />
                        <Route path="/positions" element={<RequireSchwab><Positions /></RequireSchwab>} />
                        <Route path="/transactions" element={<RequireSchwab><Transactions /></RequireSchwab>} />
                        <Route path="/allocation" element={<RequireSchwab><Reports /></RequireSchwab>} />
                        <Route path="/analyze" element={<StrikeLab />} />
                        <Route path="/charts" element={<Charts />} />
                        <Route path="/screener" element={<Screener />} />
                        <Route path="/settings" element={<Settings />} />
                      </Routes>
                      </Suspense>
                    </ErrorBoundary>
                  </main>
                </div>
                <AdminCopilot />
              </ProtectedRoute>
            }
          />
        </Routes>
        {/* Touch screens: a tapped title shows its text (no hover there). */}
        <TouchTitles />
      </BrowserRouter>
    </AuthProvider>
    </ThemeProvider>
  )
}
