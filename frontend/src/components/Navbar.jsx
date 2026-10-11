import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Menu structure: each group is a collapsible parent with its pages beneath.
const NAV_GROUPS = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    links: [
      { to: '/positions', label: 'Positions' },
      { to: '/allocation', label: 'Reports' },
      { to: '/transactions', label: 'Transactions' },
    ],
  },
  {
    id: 'market',
    label: 'Market',
    links: [
      { to: '/analyze', label: 'Analyze' },
      { to: '/charts', label: 'Charts' },
      { to: '/screener', label: 'Screener' },
    ],
  },
]

// Which groups the user has collapsed — a per-browser convenience, so every
// read/write is guarded (storage can be unavailable, e.g. private mode).
const COLLAPSED_STORAGE_KEY = 'nav-collapsed-groups'

function loadCollapsed() {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_STORAGE_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

export default function Navbar() {
  const { logout } = useAuth()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)
  const [collapsed, setCollapsed] = useState(loadCollapsed)

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
    <nav className="navbar">
      <span className="navbar-brand">
        {/* Always the light-text variant — the navbar is a dark --nav-bg in
            both themes (see tokens.css/navbar.css), matching the Copilot
            panel's titlebar, so the dark-navy "Nu" in the other variant
            would have poor contrast here either way. */}
        <img src="/nutrade_icon.svg" alt="NuTrade" className="navbar-logo" />
      </span>

      <button
        className="navbar-hamburger"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
      >
        {open ? '✕' : '☰'}
      </button>

      <div className={`navbar-links${open ? ' open' : ''}`}>
        {NAV_GROUPS.map((group) => {
          // A group holding the current page always shows it, even if the
          // user collapsed that group earlier — the active page never hides.
          const hasActive = group.links.some((l) => pathname.startsWith(l.to))
          const expanded = hasActive || !collapsed.has(group.id)
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
                <span>{group.label}</span>
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
                    >
                      {link.label}
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
          Settings
        </NavLink>
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); close() }} className="nav-link navbar-logout navbar-logout--mobile">
          Sign out
        </a>
      </div>

      {/* Settings (incl. light/dark theme) + Sign out, pinned to the bottom
          of the desktop sidebar. On phones these live inside the hamburger
          dropdown instead (the --mobile copies above). */}
      <NavLink
        to="/settings"
        className={({ isActive }) => `nav-link navbar-settings--desktop${isActive ? ' active' : ''}`}
      >
        Settings
      </NavLink>

      <a href="#" onClick={(e) => { e.preventDefault(); logout() }} className="nav-link navbar-logout navbar-logout--desktop">
        Sign out
      </a>
    </nav>
  )
}
