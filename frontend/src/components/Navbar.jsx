import { NavLink } from 'react-router-dom'

export default function Navbar() {
  return (
    <nav className="navbar">
      <span className="navbar-brand">Options Wheel</span>
      <div className="navbar-links">
        <NavLink
          to="/market"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          Market Data
        </NavLink>
        <NavLink
          to="/positions"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          Positions
        </NavLink>
        <NavLink
          to="/transactions"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          Transactions
        </NavLink>
        <NavLink
          to="/allocation"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          Monthly Gains
        </NavLink>
      </div>
    </nav>
  )
}
