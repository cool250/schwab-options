import { startSchwabReconnect } from '../api/client'
import { stashTokenForRedirect } from '../context/AuthContext'

// Start the Schwab login (Settings → Connect Schwab, and the Portfolio pages'
// "Connect Schwab" notice): a full-page navigation to Schwab, which redirects
// back to /api/auth/schwab/callback and lands on Settings. The app login is
// handed off first in case the browser drops sessionStorage on the way (see
// AuthContext). Rejects if the login URL can't be fetched.
export async function beginSchwabConnect() {
  const { url } = await startSchwabReconnect()
  stashTokenForRedirect()
  window.location.assign(url)
}
