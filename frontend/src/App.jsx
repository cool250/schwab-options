import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import CopilotWidget, { CopilotDisabledLauncher } from './components/CopilotWidget'
import RequireSchwab from './components/RequireSchwab'
import Login from './pages/Login'
import Landing from './pages/Landing'
import Positions from './pages/Positions'
import Transactions from './pages/Transactions'
import Reports from './pages/Reports'
import StrikeLab from './pages/StrikeLab'
import Charts from './pages/Charts'
import Screener from './pages/Screener'
import Settings from './pages/Settings'

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
                      <Routes>
                        {/* Portfolio pages read the user's own Schwab account —
                            RequireSchwab shows a "connect Schwab" notice first
                            if it isn't connected or has expired. */}
                        <Route path="/positions" element={<RequireSchwab><Positions /></RequireSchwab>} />
                        <Route path="/transactions" element={<RequireSchwab><Transactions /></RequireSchwab>} />
                        <Route path="/allocation" element={<RequireSchwab><Reports /></RequireSchwab>} />
                        <Route path="/analyze" element={<StrikeLab />} />
                        <Route path="/charts" element={<Charts />} />
                        <Route path="/screener" element={<Screener />} />
                        <Route path="/settings" element={<Settings />} />
                      </Routes>
                    </ErrorBoundary>
                  </main>
                </div>
                <AdminCopilot />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
    </ThemeProvider>
  )
}
