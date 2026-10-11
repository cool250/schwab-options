import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Not logged in → /login (the landing page with the login overlay open),
// remembering the page that was asked for so login can return there.
export default function ProtectedRoute({ children }) {
  const { token } = useAuth()
  const location = useLocation()
  return token ? children : <Navigate to="/login" replace state={{ from: location }} />
}
