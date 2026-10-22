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
// Screenshots in /public/landing are real captures of the app. This page is
// public, so no real account data or identity may appear in them: the
// market-data pages (Screener, Analyze and its Strategy Builder, Charts) are
// shot on live market data, and the one account page shown — Reports, the
// hero — is shot on SAMPLE P&L (its API responses mocked by the capture
// script), with the signed-in user shown as "Demo Trader". Never capture
// Positions/Transactions/Reports on real account data.

// Where login (and "Open dashboard") lands: Market → Analyze.
const DEFAULT_PAGE = '/analyze'

const FEATURES = [
  {
    Icon: PositionsIcon,
    title: 'Positions',
    text: 'Balances, stocks and options from your brokerage account, plus futures and futures options rebuilt from your trade history — with live P&L.',
  },
  {
    Icon: TransactionsIcon,
    title: 'Transactions',
    text: 'Opens and closes matched FIFO with realized P&L, ratio spreads grouped into one row, and CSV export.',
  },
  {
    Icon: ReportsIcon,
    title: 'Reports',
    text: 'Key numbers, a P&L calendar, running totals and results by symbol for any month or year to date, with click-through to the trades behind each number.',
  },
  {
    Icon: AnalyzeIcon,
    title: 'Analyze',
    text: 'A live-streaming option chain and a Strategy Builder: set up an iron condor, strangle or jade lizard by delta or moneyness, then see its payoff and time decay.',
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
    text: 'An AI assistant that can look up your positions and live market data, build strategies on the live chain, and sees the page you have open.',
  },
  {
    Icon: ShieldIcon,
    title: 'Read-only by design',
    text: 'InduTrades never places, changes or cancels an order. It only reads your account and market data.',
  },
]

const SHOWCASES = [
  {
    id: 'screener',
    eyebrow: 'Screener',
    title: 'Find the contracts worth selling',
    img: '/landing/screener.jpg',
    alt: 'InduTrades Screener ranking short puts across AAPL, MSFT, NVDA, AMZN and META by annualized ROI',
    points: [
      'Short puts and calls ranked by annualized return, long options by leverage',
      'Multi-leg scans: 1×2 ratio puts and jade lizards, priced as net credits',
      'Filter by moneyness, days to expiration and delta',
      'Tick any rows and send them straight to Analyze',
    ],
  },
  {
    id: 'strategy-builder',
    eyebrow: 'Strategy Builder',
    title: 'Build a strategy in a few clicks',
    img: '/landing/strategy-builder.jpg',
    alt: 'InduTrades Strategy Builder placing a 16-delta AAPL iron condor with $5 wings, showing its net credit, max loss, breakevens, probability of profit and each leg’s moneyness',
    points: [
      'Credit and debit strategies: short puts and calls, spreads, strangles, straddles, iron condors and butterflies, jade lizards and ratio puts',
      'Place each leg by delta, moneyness, expected move or strike, and set wings by width',
      'Set a minimum credit and it searches nearby strikes for the closest match',
      'Max profit and loss, breakevens and probability of profit, then apply it to Analyze',
    ],
  },
  {
    id: 'analyze',
    eyebrow: 'Analyze',
    title: 'See the payoff before you place it',
    img: '/landing/analyze.jpg',
    alt: 'InduTrades Analyze showing an AAPL iron condor built with the Strategy Builder, with its payoff graph, net credit, max loss and breakevens',
    points: [
      'Live, streaming option chain',
      'Start from the Strategy Builder, or click any bid or ask to add a leg',
      'Net credit, max profit and loss, and breakevens update as you edit legs',
      'Payoff graph plus a strike-by-date table of time decay',
    ],
  },
  {
    id: 'charts',
    eyebrow: 'Charts',
    title: 'Price context at a glance',
    img: '/landing/charts.jpg',
    alt: 'InduTrades Charts showing six months of AAPL daily candles with support and resistance lines',
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
        <img src="/indutrades_logo.svg" alt="InduTrades" className="login-logo" />
        <p className="login-subtitle" id="register-title">Create an account</p>
      </div>
      {/* No self-service sign-up: the admin creates accounts (Settings →
          Users, api/admin.py), so this explains that rather than showing a
          form that can't do anything. */}
      <p className="landing-register-text">
        InduTrades is invite-only. Accounts are created by the admin — ask them for a username and password, then
        log in. You can change your password in Settings after you sign in.
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
    // Back to the page that sent the visitor to /login, else the Market
    // section's first page — it works for every user right away, unlike
    // the Portfolio pages, which need the user's own Schwab connection.
    const from = location.state?.from
    navigate(from?.pathname ? `${from.pathname}${from.search ?? ''}` : DEFAULT_PAGE, { replace: true })
  }

  const authActions = token ? (
    <Link to={DEFAULT_PAGE} className="btn btn-primary">Open dashboard</Link>
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
          <img src="/indutrades_logo.svg" alt="InduTrades" className="landing-logo" />
          <nav className="landing-nav" aria-label="Page sections">
            <a href="#features">Features</a>
            <a href="#screener">Screener</a>
            <a href="#strategy-builder">Strategy Builder</a>
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
              <p className="landing-eyebrow">Built for premium sellers</p>
              <h1>Run your options strategy with every number in one place.</h1>
              <p className="landing-lede">
                InduTrades brings your positions and trade history, live option chains, a strategy builder, a strike
                analyzer and an options screener into one read-only dashboard — with an AI copilot that knows
                what you're looking at.
              </p>
              <div className="landing-hero-actions">
                {token ? (
                  <Link to={DEFAULT_PAGE} className="btn btn-primary landing-cta">Open dashboard</Link>
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
                src="/landing/reports.jpg"
                alt="InduTrades Reports showing a month's P&L, win rate and profit factor, a P&L calendar and a running total (sample data)"
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
      </main>

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
