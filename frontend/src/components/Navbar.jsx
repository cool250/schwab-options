import { useState, useEffect } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  PortfolioIcon, MarketIcon, PositionsIcon, ReportsIcon, TransactionsIcon,
  AnalyzeIcon, ChartsIcon, ScreenerIcon, SettingsIcon, SignOutIcon, CollapseIcon,
} from './NavIcons'

// Menu structure: each group is a collapsible parent with its pages beneath.
const NAV_GROUPS = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    Icon: PortfolioIcon,
    links: [
      { to: '/positions', label: 'Positions', Icon: PositionsIcon },
      { to: '/allocation', label: 'Reports', Icon: ReportsIcon },
      { to: '/transactions', label: 'Transactions', Icon: TransactionsIcon },
    ],
  },
  {
    id: 'market',
    label: 'Market',
    Icon: MarketIcon,
    links: [
      { to: '/analyze', label: 'Analyze', Icon: AnalyzeIcon },
      { to: '/charts', label: 'Charts', Icon: ChartsIcon },
      { to: '/screener', label: 'Screener', Icon: ScreenerIcon },
    ],
  },
]

// Which groups the user has collapsed — a per-browser convenience, so every
// read/write is guarded (storage can be unavailable, e.g. private mode).
const COLLAPSED_STORAGE_KEY = 'nav-collapsed-groups'

// Desktop sidebar collapsed to an icon-only rail — also per-browser.
const RAIL_STORAGE_KEY = 'nav-sidebar-collapsed'

function loadRail() {
  let rail = false
  try {
    rail = localStorage.getItem(RAIL_STORAGE_KEY) === '1'
  } catch {}
  // Apply before the first paint (this runs in useState's initializer), so
  // a page loaded with the menu collapsed doesn't visibly slide from the
  // full width to the rail.
  document.documentElement.classList.toggle('sidebar-collapsed', rail)
  return rail
}

function loadCollapsed() {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_STORAGE_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

export default function Navbar() {
  const { logout, user } = useAuth()
  const navigate = useNavigate()
  // Sign out lands on the public landing page rather than letting
  // ProtectedRoute bounce to /login, which would open the login overlay.
  const signOut = () => {
    navigate('/', { replace: true })
    logout()
  }
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)
  const [collapsed, setCollapsed] = useState(loadCollapsed)
  const [rail, setRail] = useState(loadRail)

  // The rail width lives in --sidebar-width (navbar.css), which also sets
  // .app-shell's left padding — so the page reflows to the narrower menu.
  useEffect(() => {
    try {
      localStorage.setItem(RAIL_STORAGE_KEY, rail ? '1' : '0')
    } catch {}
    document.documentElement.classList.toggle('sidebar-collapsed', rail)
  }, [rail])

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify([...collapsed]))
    } catch {}
  }, [collapsed])

  function toggleGroup(id) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <nav className={`navbar${rail ? ' navbar--rail' : ''}`}>
      <div className="navbar-brand">
        {/* Always the light-text variant — the navbar is a dark --nav-bg in
            both themes (see tokens.css/navbar.css), matching the Copilot
            panel's titlebar, so the dark-navy "Nu" in the other variant
            would have poor contrast here either way. */}
        <img src="/nutrade_icon.svg" alt="NuTrade" className="navbar-logo" />
        {/* Desktop-only: collapse the sidebar to an icon rail and back. */}
        <button
          type="button"
          className="navbar-rail-toggle"
          onClick={() => setRail((r) => !r)}
          aria-label={rail ? 'Expand menu' : 'Collapse menu'}
          aria-pressed={rail}
          title={rail ? 'Expand menu' : 'Collapse menu'}
        >
          <CollapseIcon />
        </button>
      </div>

      <button
        className="navbar-hamburger"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
      >
        {open ? '✕' : '☰'}
      </button>

      <div className={`navbar-links${open ? ' open' : ''}`}>
        <NavUser user={user} className="navbar-user--mobile" />
        {NAV_GROUPS.map((group) => {
          // A group holding the current page always shows it, even if the
          // user collapsed that group earlier — the active page never hides.
          const hasActive = group.links.some((l) => pathname.startsWith(l.to))
          // In the icon rail there are no group headers to expand, so every
          // page icon is always shown.
          const expanded = rail || hasActive || !collapsed.has(group.id)
          const listId = `nav-group-${group.id}`
          return (
            <div key={group.id} className="nav-group">
              <button
                type="button"
                className={`nav-group-toggle${hasActive ? ' has-active' : ''}`}
                aria-expanded={expanded}
                aria-controls={listId}
                onClick={() => toggleGroup(group.id)}
                disabled={hasActive}
                title={hasActive ? undefined : expanded ? `Collapse ${group.label}` : `Expand ${group.label}`}
              >
                <span className="nav-group-label">
                  <group.Icon />
                  <span className="nav-label">{group.label}</span>
                </span>
                <span className={`nav-group-chevron${expanded ? ' expanded' : ''}`} aria-hidden="true">›</span>
              </button>
              {expanded && (
                <div id={listId} className="nav-group-links">
                  {group.links.map((link) => (
                    <NavLink
                      key={link.to}
                      to={link.to}
                      className={({ isActive }) => `nav-link nav-sublink${isActive ? ' active' : ''}`}
                      onClick={close}
                      title={rail ? link.label : undefined}
                      aria-label={link.label}
                    >
                      <link.Icon />
                      <span className="nav-label">{link.label}</span>
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        <NavLink
          to="/settings"
          className={({ isActive }) => `nav-link navbar-settings--mobile${isActive ? ' active' : ''}`}
          onClick={close}
        >
          <SettingsIcon />
          Settings
        </NavLink>
        <a href="#" onClick={(e) => { e.preventDefault(); signOut(); close() }} className="nav-link navbar-logout navbar-logout--mobile">
          <SignOutIcon />
          Sign out
        </a>
      </div>

      {/* Who's signed in, Settings (incl. light/dark theme) and Sign out,
          pinned to the bottom of the desktop sidebar. On phones these live
          inside the hamburger dropdown instead (the --mobile copies above). */}
      <NavUser user={user} className="navbar-user--desktop" />
      <NavLink
        to="/settings"
        className={({ isActive }) => `nav-link navbar-settings--desktop${isActive ? ' active' : ''}`}
        title={rail ? 'Settings' : undefined}
        aria-label="Settings"
      >
        <SettingsIcon />
        <span className="nav-label">Settings</span>
      </NavLink>

      <a
        href="#"
        onClick={(e) => { e.preventDefault(); signOut() }}
        className="nav-link navbar-logout navbar-logout--desktop"
        title={rail ? 'Sign out' : undefined}
        aria-label="Sign out"
      >
        <SignOutIcon />
        <span className="nav-label">Sign out</span>
      </a>
    </nav>
  )
}

// The signed-in user: initials avatar plus their name (first/last from the
// profile, else the username) and role. In the icon rail only the avatar
// shows; the tooltip carries the full name either way (long names truncate).
function NavUser({ user, className }) {
  if (!user) return null
  const name = [user.firstName, user.lastName].filter(Boolean).join(' ') || user.username
  const initials = (user.firstName || user.lastName)
    ? `${user.firstName?.[0] ?? ''}${user.lastName?.[0] ?? ''}`
    : user.username.slice(0, 2)
  return (
    <div className={`navbar-user ${className}`} title={`Signed in as ${name}`}>
      <span className="navbar-user-avatar" aria-hidden="true">{initials.toUpperCase()}</span>
      <span className="navbar-user-text nav-label">
        <span className="navbar-user-name">{name}</span>
        <span className="navbar-user-role">{user.isAdmin ? 'Admin' : 'User'}</span>
      </span>
    </div>
  )
}
