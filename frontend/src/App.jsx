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
                    </Routes>
                  </ErrorBoundary>
                </main>
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
