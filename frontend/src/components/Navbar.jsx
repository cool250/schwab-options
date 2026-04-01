import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Navbar() {
  const { logout } = useAuth()
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)

  return (
    <nav className="navbar">
      <span className="navbar-brand">
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
        <NavLink to="/market"       className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Market Data</NavLink>
        <NavLink to="/positions"    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Positions</NavLink>
        <NavLink to="/transactions" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Transactions</NavLink>
        <NavLink to="/allocation"   className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Monthly Gains</NavLink>
        <NavLink to="/optimizer"    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} onClick={close}>Optimizer</NavLink>
        <button onClick={() => { logout(); close() }} className="btn btn-secondary navbar-logout navbar-logout--mobile">
          Sign out
        </button>
      </div>

      <button onClick={logout} className="btn btn-secondary navbar-logout navbar-logout--desktop">
        Sign out
      </button>
    </nav>
  )
}
