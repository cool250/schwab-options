import { useState, useEffect } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  PortfolioIcon, MarketIcon, HomeIcon, PositionsIcon, ReportsIcon, TransactionsIcon,
  AnalyzeIcon, ChartsIcon, ScreenerIcon, SettingsIcon, SignOutIcon, CollapseIcon, MoreIcon,
} from './NavIcons'

// Menu structure: each group is a collapsible parent with its pages beneath.
const NAV_GROUPS = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    Icon: PortfolioIcon,
    links: [
      { to: '/home', label: 'Home', Icon: HomeIcon },
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

// The phone's bottom tab bar: the pages checked most on a phone, then "More"
// (the rest of the menu, opened as a sheet above the bar).
const TAB_LINKS = [
  { to: '/home', label: 'Home', Icon: HomeIcon },
  { to: '/positions', label: 'Positions', Icon: PositionsIcon },
  { to: '/allocation', label: 'Reports', Icon: ReportsIcon },
  { to: '/analyze', label: 'Analyze', Icon: AnalyzeIcon },
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
  const inTabs = TAB_LINKS.some((l) => pathname.startsWith(l.to))

  // The phone's More sheet closes on navigation and on Escape.
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    // copilot.css hides the floating copilot button over the open sheet.
    document.documentElement.classList.toggle('nav-sheet-open', open)
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

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
        <img src="/indutrades_logo.svg" alt="InduTrades" className="navbar-logo" />
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

      {/* Phones: a bottom tab bar in place of the sidebar. */}
      <div className="navbar-tabs">
        {TAB_LINKS.map((link) => (
          <NavLink key={link.to} to={link.to} className={({ isActive }) => `navbar-tab${isActive && !open ? ' active' : ''}`}>
            <link.Icon />
            <span>{link.label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          className={`navbar-tab${open || !inTabs ? ' active' : ''}`}
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="navbar-menu"
        >
          <MoreIcon />
          <span>More</span>
        </button>
      </div>
      {open && <div className="navbar-sheet-backdrop" onClick={close} aria-hidden="true" />}

      <div id="navbar-menu" className={`navbar-links${open ? ' open' : ''}`}>
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
          in the More sheet instead (the --mobile copies above). */}
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
