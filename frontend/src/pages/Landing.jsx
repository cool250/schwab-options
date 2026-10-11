import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LoginCard } from '../components/LoginCard'
import {
  PositionsIcon, TransactionsIcon, ReportsIcon, AnalyzeIcon,
  ChartsIcon, ScreenerIcon, ShieldIcon,
} from '../components/NavIcons'
import { CopilotIcon } from '../components/CopilotWidget'

// Public landing page at "/" (and at /login, with the login overlay open).
// Screenshots in /public/landing are real captures of the market-data
// pages only — Screener, Analyze, Charts — never Positions/Transactions/
// Reports, since this page is public and those show account data.

const FEATURES = [
  {
    Icon: PositionsIcon,
    title: 'Positions',
    text: 'Balances, stocks and options from Schwab, plus futures and futures options rebuilt from your trade history — with live P&L.',
  },
  {
    Icon: TransactionsIcon,
    title: 'Transactions',
    text: 'Opens and closes matched FIFO with realized P&L, ratio spreads grouped into one row, and CSV export.',
  },
  {
    Icon: ReportsIcon,
    title: 'Reports',
    text: 'P&L by symbol, week and day for any month or year to date, with click-through to the trades behind each number.',
  },
  {
    Icon: AnalyzeIcon,
    title: 'Analyze',
    text: 'A live-streaming option chain: click a bid or ask to build a position, then see its payoff graph and time decay.',
  },
  {
    Icon: ChartsIcon,
    title: 'Charts',
    text: 'Candles from one day to twenty years, with swing support and resistance and put/call sentiment gauges.',
  },
  {
    Icon: ScreenerIcon,
    title: 'Screener',
    text: 'Scan a watchlist for the best puts and calls to sell — or buy — including ratio puts and jade lizards.',
  },
  {
    Icon: () => <CopilotIcon size={18} />,
    title: 'Copilot',
    text: 'An AI assistant that can look up your positions and live market data, and sees the page you have open.',
  },
  {
    Icon: ShieldIcon,
    title: 'Read-only by design',
    text: 'NuTrade never places, changes or cancels an order. It only reads your account and market data.',
  },
]

const SHOWCASES = [
  {
    id: 'screener',
    eyebrow: 'Screener',
    title: 'Find the contracts worth selling',
    img: '/landing/screener.jpg',
    alt: 'NuTrade Screener ranking short puts across AAPL, MSFT, NVDA, AMZN and META by annualized ROI',
    points: [
      'Short puts and calls ranked by annualized return, long options by leverage',
      'Multi-leg scans: 1×2 ratio puts and jade lizards, priced as net credits',
      'Filter by moneyness, days to expiration and delta',
      'Tick any rows and send them straight to Analyze',
    ],
  },
  {
    id: 'analyze',
    eyebrow: 'Analyze',
    title: 'See the payoff before you place it',
    img: '/landing/analyze.jpg',
    alt: 'NuTrade Analyze showing a short AAPL 335 put with its payoff graph, net credit, max loss and breakeven',
    points: [
      'Live option chain streamed from Tastytrade',
      'Net credit, max profit and loss, and breakevens update as you edit legs',
      'Payoff graph plus a strike-by-date table of time decay',
    ],
  },
  {
    id: 'charts',
    eyebrow: 'Charts',
    title: 'Price context at a glance',
    img: '/landing/charts.jpg',
    alt: 'NuTrade Charts showing six months of AAPL daily candles with support and resistance lines',
    points: [
      'Ranges from 1 day to 20 years, stocks and futures',
      'Swing support and resistance drawn on every range',
      'Put/call ratio and implied-volatility gauges for the nearest expiration',
    ],
  },
]

function Overlay({ onClose, labelledBy, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  return (
    <div className="landing-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        {children}
      </div>
    </div>
  )
}

function RegisterCard({ onClose, onLogin }) {
  return (
    <div className="login-card">
      <button type="button" className="login-close" onClick={onClose} aria-label="Close">×</button>
      <div className="login-header">
        <img src="/nutrade_icon.svg" alt="NuTrade" className="login-logo" />
        <p className="login-subtitle" id="register-title">Create an account</p>
      </div>
      {/* NuTrade is a single-user app today: one admin login configured on
          the server, no user accounts to create — so this explains that
          rather than showing a sign-up form that can't do anything. */}
      <p className="landing-register-text">
        NuTrade is invite-only for now — new accounts can't be created yet. If you already have access, log in
        with the credentials you were given.
      </p>
      <button type="button" className="btn btn-primary login-btn" onClick={onLogin}>Log in instead</button>
    </div>
  )
}

export default function Landing({ initialOverlay = null }) {
  const { token } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [overlay, setOverlay] = useState(initialOverlay) // null | 'login' | 'register'

  // Arriving via /login keeps the URL in sync when the overlay closes.
  function closeOverlay() {
    setOverlay(null)
    if (location.pathname === '/login') navigate('/', { replace: true })
  }

  function afterLogin() {
    // Back to the page that sent the visitor to /login, else Positions.
    const from = location.state?.from
    navigate(from?.pathname ? `${from.pathname}${from.search ?? ''}` : '/positions', { replace: true })
  }

  const authActions = token ? (
    <Link to="/positions" className="btn btn-primary">Open dashboard</Link>
  ) : (
    <>
      <button type="button" className="landing-link-btn" onClick={() => setOverlay('login')}>Log in</button>
      <button type="button" className="btn btn-primary" onClick={() => setOverlay('register')}>Register</button>
    </>
  )

  return (
    <div className="landing">
      <header className="landing-header">
        <div className="landing-container landing-header-inner">
          <img src="/nutrade_icon.svg" alt="NuTrade" className="landing-logo" />
          <nav className="landing-nav" aria-label="Page sections">
            <a href="#features">Features</a>
            <a href="#screener">Screener</a>
            <a href="#analyze">Analyze</a>
            <a href="#charts">Charts</a>
          </nav>
          <div className="landing-header-actions">{authActions}</div>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-container landing-hero-inner">
            <div className="landing-hero-copy">
              <p className="landing-eyebrow">Options strategy dashboard</p>
              <h1>Run your options strategy with every number in one place.</h1>
              <p className="landing-lede">
                NuTrade brings your Schwab positions and trade history, live Tastytrade option chains, a strike
                analyzer and an options screener into one read-only dashboard — with an AI copilot that knows
                what you're looking at.
              </p>
              <div className="landing-hero-actions">
                {token ? (
                  <Link to="/positions" className="btn btn-primary landing-cta">Open dashboard</Link>
                ) : (
                  <>
                    <button type="button" className="btn btn-primary landing-cta" onClick={() => setOverlay('login')}>
                      Log in
                    </button>
                    <button type="button" className="btn landing-cta landing-cta--ghost" onClick={() => setOverlay('register')}>
                      Register
                    </button>
                  </>
                )}
              </div>
            </div>
            <figure className="landing-shot landing-shot--hero">
              <img
                src="/landing/screener.jpg"
                alt="NuTrade Screener ranking short puts by annualized ROI"
                width="1600"
                height="1000"
              />
            </figure>
          </div>
        </section>

        <section id="features" className="landing-section">
          <div className="landing-container">
            <h2 className="landing-section-title">Everything for your options strategy, in one dashboard</h2>
            <p className="landing-section-sub">From the trades you've made to the ones you're considering.</p>
            <ul className="landing-features">
              {FEATURES.map(({ Icon, title, text }) => (
                <li key={title} className="landing-feature">
                  <span className="landing-feature-icon" aria-hidden="true"><Icon /></span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {SHOWCASES.map((s, i) => (
          <section key={s.id} id={s.id} className={`landing-section landing-showcase${i % 2 ? ' landing-showcase--flip' : ''}`}>
            <div className="landing-container landing-showcase-inner">
              <div className="landing-showcase-copy">
                <p className="landing-eyebrow landing-eyebrow--muted">{s.eyebrow}</p>
                <h2>{s.title}</h2>
                <ul>
                  {s.points.map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
              <figure className="landing-shot">
                <img src={s.img} alt={s.alt} width="1600" height="1000" loading="lazy" />
              </figure>
            </div>
          </section>
        ))}

        <section className="landing-cta-band">
          <div className="landing-container landing-cta-band-inner">
            <h2>Ready to look at your book?</h2>
            <div className="landing-hero-actions">{authActions}</div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-container landing-footer-inner">
          <img src="/nutrade_icon.svg" alt="NuTrade" className="landing-footer-logo" />
          <p>Read-only by design · Market data from Tastytrade · Account data from Schwab</p>
        </div>
      </footer>

      {overlay === 'login' && (
        <Overlay onClose={closeOverlay} labelledBy="login-title">
          <LoginCard onSuccess={afterLogin} onClose={closeOverlay} />
        </Overlay>
      )}
      {overlay === 'register' && (
        <Overlay onClose={closeOverlay} labelledBy="register-title">
          <RegisterCard onClose={closeOverlay} onLogin={() => setOverlay('login')} />
        </Overlay>
      )}
    </div>
  )
}
