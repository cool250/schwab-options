import Landing from './Landing'

/** /login — where ProtectedRoute sends a logged-out visitor: the landing
 *  page with the login overlay (components/LoginCard.jsx) already open. */
export default function Login() {
  return <Landing initialOverlay="login" />
}
