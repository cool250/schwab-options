import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Navbar from './components/Navbar'
import CopilotWidget from './components/CopilotWidget'
import Login from './pages/Login'
import Positions from './pages/Positions'
import Transactions from './pages/Transactions'
import Reports from './pages/Reports'
import StrikeLab from './pages/StrikeLab'
import Charts from './pages/Charts'
import Screener from './pages/Screener'
import Settings from './pages/Settings'

export default function App() {
  return (
    <ThemeProvider>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
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
                        <Route path="/" element={<Navigate to="/positions" replace={true} />} />
                        <Route path="/positions" element={<Positions />} />
                        <Route path="/transactions" element={<Transactions />} />
                        <Route path="/allocation" element={<Reports />} />
                        <Route path="/analyze" element={<StrikeLab />} />
                        <Route path="/charts" element={<Charts />} />
                        <Route path="/screener" element={<Screener />} />
                        <Route path="/settings" element={<Settings />} />
                      </Routes>
                    </ErrorBoundary>
                  </main>
                </div>
                <CopilotWidget />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
    </ThemeProvider>
  )
}
