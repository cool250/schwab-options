import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'

export default function Navbar() {
  const { logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)

  return (
    <nav className="navbar">
      <span className="navbar-brand">
        <img
          src={theme === 'dark' ? '/nutrade_icon_dark.svg' : '/nutrade_icon.svg'}
          alt="NuTrade"
          className="navbar-logo"
        />
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
        <NavLink to="/positions"    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Positions</NavLink>
        <NavLink to="/transactions" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Transactions</NavLink>
        <NavLink to="/allocation"   className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Reports</NavLink>
        <NavLink to="/analyze"    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Analyze</NavLink>
        <NavLink to="/charts"     className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Charts</NavLink>
        <a href="#" onClick={(e) => { e.preventDefault(); toggleTheme() }} className="nav-link navbar-theme-toggle--mobile">
          {theme === 'dark' ? '☀️ Light mode' : '🌙 Dark mode'}
        </a>
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); close() }} className="navbar-logout navbar-logout--mobile">
          Sign out
        </a>
      </div>

      <button
        type="button"
        className="navbar-theme-toggle--desktop"
        onClick={toggleTheme}
        aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {theme === 'dark' ? '☀️' : '🌙'}
      </button>

      <a href="#" onClick={(e) => { e.preventDefault(); logout() }} className="navbar-logout navbar-logout--desktop">
        Sign out
      </a>
    </nav>
  )
}
