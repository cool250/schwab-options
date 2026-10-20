import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { screenOptions, getScreenerStrategies, friendlyErrorMessage } from '../api/client'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { formatDate } from '../utils/dateFormat'
import { setCopilotContext, clearCopilotContext } from '../utils/copilotContext'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'
import HelpTip from '../components/HelpTip'
import { createSessionCache } from '../utils/sessionCaches'

// Survives navigating away and back within a session (same pattern as
// strikeLabCache in StrikeLab.jsx) — a screen across several tickers takes
// a few seconds, so losing it on a quick detour to another page would hurt.
const DEFAULT_CRITERIA = {
  tickers: '',
  minMoneyness: 0,
  maxMoneyness: 3,
  minDte: 0,
  maxDte: 7,
  minDelta: '',
  maxDelta: '',
  optionType: 'PUT', // a screener strategy id (SINGLE_LEG or a fetched template)
}

// Dropdown choices come from GET /market/options/screener/strategies: the
// single contracts below, then every multi-leg credit template from the
// Strategy Builder (service/market/screener_strategies.py), under the same
// names. The single contracts are also the fallback until that loads.
const SINGLE_LEG = [
  { id: 'PUT', name: 'Short Puts', kind: 'short' },
  { id: 'CALL', name: 'Short Calls', kind: 'short' },
  { id: 'LONG_PUT', name: 'Long Puts', kind: 'long' },
  { id: 'LONG_CALL', name: 'Long Calls', kind: 'long' },
]
const LONG = ['LONG_PUT', 'LONG_CALL']
const isMultiLeg = (strategy) => strategy != null && !SINGLE_LEG.some((s) => s.id === strategy)

const screenerCache = createSessionCache(() => ({
  criteria: DEFAULT_CRITERIA,
  result: null,
  // Rows ticked for Analyze Selected — kept with `result` so they're still
  // ticked after a trip to Analyze and back.
  selected: new Map(),
}))

// A blank field becomes null — for delta that means "no limit on that side"
// (distinct from an explicit 0); for moneyness it's rejected as missing.
// NaN flags a non-number.
function optionalNumber(value) {
  // null/undefined count as blank too — String(undefined) would otherwise
  // become the non-number "undefined" (e.g. criteria restored from before a
  // field existed).
  if (value == null) return null
  const text = String(value).trim()
  return text === '' ? null : Number(text)
}

function parseTickers(text) {
  return [...new Set(text.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean))]
}

const num = (v, digits = 2) =>
  v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
const pct = (v, digits = 2) => (v == null ? '—' : `${num(v, digits)}%`)
const signClass = (v) => (v > 0 ? 'cell-positive' : v < 0 ? 'cell-negative' : '')
const int = (v) => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }))

// Same router-state handoff as Positions' "Analyze Selected" (StrikeLab
// reads location.state.analyzePositions on mount; negative quantity =
// sold). A short contract arrives as a 1-lot short leg priced at the bid, a
// long contract as a 1-lot long leg at the ask; a strategy row arrives as
// all of its legs, each at the price its columns assume (bid for a short
// leg, ask for a long one).
function toAnalyzePositions(row) {
  const common = { symbol: row.underlying, ticker: row.underlying, dte: row.dte, expirationDate: row.expirationDate }
  if (row.legs) {
    return row.legs.map((leg) => ({
      ...common, strike: leg.strike, optionType: leg.type, quantity: leg.qty, premium: leg.price,
    }))
  }
  if (LONG.includes(row.strategy)) {
    return [{ ...common, strike: row.strike, optionType: row.type, quantity: 1, premium: row.ask }]
  }
  return [{ ...common, strike: row.strike, optionType: row.type, quantity: -1, premium: row.bid }]
}

// "+1 335P −2 325P" — compact leg list for a strategy row (strike trailing
// zeros dropped the same way formatOptionSymbol does).
function legsLabel(legs) {
  return legs
    .map((l) => `${l.qty > 0 ? '+' : '−'}${Math.abs(l.qty)} ${l.strike.toFixed(2).replace(/\.?0+$/, '')}${l.type === 'PUT' ? 'P' : 'C'}`)
    .join(' ')
}

function rowLabel(r) {
  return r.legs
    ? `${r.underlying} ${formatDate(r.expirationDate)} ${legsLabel(r.legs)}`
    : formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type) ?? r.symbol
}

const COLUMNS = [
  {
    key: 'symbol',
    label: 'Contract',
    render: (r) => formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type) ?? r.symbol,
  },
  { key: 'type', label: 'Type', render: (r) => (r.type === 'PUT' ? 'Put' : 'Call') },
  { key: 'expirationDate', label: 'Expiration', render: (r) => formatDate(r.expirationDate) },
  { key: 'dte', label: 'DTE', align: 'right' },
  { key: 'strike', label: 'Strike', align: 'right', render: (r) => num(r.strike) },
  { key: 'spot', label: 'Spot', align: 'right', render: (r) => num(r.spot) },
  { key: 'otmPct', label: 'OTM %', align: 'right', render: (r) => pct(r.otmPct, 1) },
  { key: 'bid', label: 'Bid', align: 'right', render: (r) => num(r.bid) },
  { key: 'ask', label: 'Ask', align: 'right', render: (r) => num(r.ask) },
  { key: 'delta', label: 'Delta', align: 'right', render: (r) => num(r.delta) },
  { key: 'iv', label: 'IV', align: 'right', render: (r) => (r.iv == null ? '—' : pct(r.iv * 100, 1)) },
  { key: 'openInterest', label: 'Open Int', align: 'right', render: (r) => int(r.openInterest) },
  { key: 'volume', label: 'Volume', align: 'right', render: (r) => int(r.volume) },
  { key: 'breakeven', label: 'Breakeven', align: 'right', render: (r) => num(r.breakeven) },
  { key: 'roi', label: 'ROI', align: 'right', render: (r) => <span className="cell-positive">{pct(r.roi)}</span> },
  {
    key: 'annualizedRoi',
    label: 'Ann. ROI',
    align: 'right',
    render: (r) => <span className="cell-positive screener-ann-roi">{pct(r.annualizedRoi, 1)}</span>,
  },
]

// Multi-leg strategy rows — one row per combination. Credit, max profit,
// breakeven and capital are per share, like the single-contract columns.
const STRATEGY_COLUMNS = [
  {
    key: 'symbol',
    label: 'Position',
    render: (r) => (
      <span className="screener-position">
        <span>{r.underlying}</span> <span className="screener-legs">{legsLabel(r.legs)}</span>
      </span>
    ),
  },
  { key: 'expirationDate', label: 'Expiration', render: (r) => formatDate(r.expirationDate) },
  { key: 'dte', label: 'DTE', align: 'right' },
  { key: 'spot', label: 'Spot', align: 'right', render: (r) => num(r.spot) },
  { key: 'shortDelta', label: 'Short Δ', align: 'right', render: (r) => num(r.shortDelta) },
  { key: 'credit', label: 'Credit', align: 'right', render: (r) => num(r.credit) },
  { key: 'maxProfit', label: 'Max Profit', align: 'right', render: (r) => num(r.maxProfit) },
  {
    key: 'lowerBreakeven',
    label: 'Breakeven',
    align: 'right',
    render: (r) => (r.breakevens?.length ? r.breakevens.map((b) => num(b)).join(' / ') : '—'),
  },
  { key: 'capital', label: 'Capital', align: 'right', render: (r) => num(r.capital) },
  // Unlike a single OTM contract, a combination can be losing at today's
  // price (e.g. an ITM credit spread), so color by sign.
  { key: 'roi', label: 'ROI', align: 'right', render: (r) => <span className={signClass(r.roi)}>{pct(r.roi)}</span> },
  {
    key: 'annualizedRoi',
    label: 'Ann. ROI',
    align: 'right',
    render: (r) => <span className={`${signClass(r.annualizedRoi)} screener-ann-roi`}>{pct(r.annualizedRoi, 1)}</span>,
  },
]

// Long Puts / Long Calls — bought at the ask, ranked by leverage (λ) rather
// than ROI, which assumes an unchanged price and so doesn't fit a long option.
const LONG_COLUMNS = [
  ...COLUMNS.filter((c) => !['breakeven', 'roi', 'annualizedRoi'].includes(c.key)),
  { key: 'breakeven', label: 'Breakeven', align: 'right', render: (r) => num(r.breakeven) },
  { key: 'breakevenMovePct', label: 'BE Move %', align: 'right', render: (r) => pct(r.breakevenMovePct, 1) },
  {
    key: 'leverage',
    label: 'Leverage (λ)',
    align: 'right',
    render: (r) => <span className="screener-ann-roi">{r.leverage == null ? '—' : `${num(r.leverage, 1)}×`}</span>,
  },
]

export default function Screener() {
  const navigate = useNavigate()
  // Defaults first, so a field added since the cached criteria were saved
  // starts at its default instead of undefined.
  const [criteria, setCriteria] = useState(() => {
    const merged = { ...DEFAULT_CRITERIA, ...screenerCache.criteria }
    if (typeof merged.optionType !== 'string') merged.optionType = DEFAULT_CRITERIA.optionType
    return merged
  })
  const [strategies, setStrategies] = useState(SINGLE_LEG)
  const strategyName = (id) => strategies.find((s) => s.id === id)?.name ?? id

  useEffect(() => {
    let cancelled = false
    getScreenerStrategies()
      .then((list) => {
        if (cancelled) return
        setStrategies(list)
        // A value from an older version of this page (e.g. the removed
        // 'BOTH') falls back to the default rather than leaving the
        // dropdown blank.
        setCriteria((c) => (list.some((s) => s.id === c.optionType) ? c : { ...c, optionType: DEFAULT_CRITERIA.optionType }))
      })
      .catch(() => {}) // keep the single-contract choices
    return () => { cancelled = true }
  }, [])
  const [result, setResult] = useState(screenerCache.result)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  // Selected result rows, keyed by contract symbol (unique per row).
  const [selected, setSelected] = useState(() => new Map(screenerCache.selected))
  const [analyzeError, setAnalyzeError] = useState(null)

  useEffect(() => {
    screenerCache.criteria = criteria
  }, [criteria])

  useEffect(() => {
    screenerCache.result = result
  }, [result])

  useEffect(() => {
    screenerCache.selected = selected
  }, [selected])

  function toggleSelected(row) {
    setSelected((prev) => {
      const next = new Map(prev)
      if (next.has(row.symbol)) next.delete(row.symbol)
      else next.set(row.symbol, row)
      return next
    })
  }

  // Same rule as Positions: StrikeLab's payoff graph prices one spot for one
  // underlying at one point in time, so legs must share both — checked up
  // front rather than letting Analyze plot a nonsensical mix. A put and a
  // call on the same ticker/expiration (e.g. a short strangle) is fine, and
  // a strategy row's legs always share both already.
  function handleAnalyzeSelected() {
    const rows = Array.from(selected.values())
    const tickers = new Set(rows.map((r) => r.underlying))
    const expirations = new Set(rows.map((r) => r.expirationDate))
    if (tickers.size > 1 || expirations.size > 1) {
      setAnalyzeError('Select options for a single ticker and expiration date to analyze together.')
      return
    }
    setAnalyzeError(null)
    navigate('/analyze', { state: { analyzePositions: rows.flatMap(toAnalyzePositions), view: 'graph' } })
  }

  // Lets the copilot answer "which of these would you pick?" about the
  // screen on the page — the top rows only, to keep the prompt small.
  useEffect(() => {
    if (!result) {
      clearCopilotContext('Screener')
      return
    }
    setCopilotContext('Screener', {
      criteria: result.criteria,
      totalMatches: result.totalMatches,
      topResults: result.results.slice(0, 20).map((r) => r.legs ? ({
        strategy: r.strategy,
        position: rowLabel(r),
        dte: r.dte,
        spot: r.spot,
        legs: r.legs.map(({ type, strike, qty, price, delta }) => ({ type, strike, qty, price, delta })),
        creditPerShare: r.credit,
        maxProfitPerShare: r.maxProfit,
        breakevens: r.breakevens,
        capitalPerShare: r.capital,
        roiPct: r.roi,
        annualizedRoiPct: r.annualizedRoi,
      }) : ({
        strategy: r.strategy,
        contract: formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type),
        dte: r.dte,
        spot: r.spot,
        otmPct: r.otmPct,
        bid: r.bid,
        ask: r.ask,
        delta: r.delta,
        iv: r.iv,
        openInterest: r.openInterest,
        roiPct: r.roi,
        annualizedRoiPct: r.annualizedRoi,
        leverage: r.leverage,
        breakevenMovePct: r.breakevenMovePct,
      })),
    })
    return () => clearCopilotContext('Screener')
  }, [result])

  const update = (field) => (e) =>
    setCriteria((c) => ({ ...c, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    const symbols = parseTickers(criteria.tickers)
    const strategy = criteria.optionType
    const minDte = Number(criteria.minDte)
    const maxDte = Number(criteria.maxDte)
    const minMoneyness = optionalNumber(criteria.minMoneyness)
    const maxMoneyness = optionalNumber(criteria.maxMoneyness)
    const minDelta = optionalNumber(criteria.minDelta)
    const maxDelta = optionalNumber(criteria.maxDelta)

    const problem =
      symbols.length === 0 ? 'Enter at least one ticker.'
      : symbols.length > 25 ? 'Screen at most 25 tickers at a time.'
      : ![minDte, maxDte].every(Number.isFinite) ? 'DTE must be a number.'
      : minMoneyness == null || maxMoneyness == null ? 'Enter both a min and max moneyness.'
      : ![minMoneyness, maxMoneyness].every(Number.isFinite) ? 'Moneyness must be a number.'
      : ![minDelta, maxDelta].every((v) => v == null || Number.isFinite(v)) ? 'Delta must be a number (or left blank).'
      : minDte < 0 || maxDte > 365 ? 'DTE must be between 0 and 365.'
      : minDte > maxDte ? 'Min DTE must not exceed Max DTE.'
      : minMoneyness < -100 || maxMoneyness > 100 ? 'Moneyness must be between -100% and 100%.'
      : minMoneyness > maxMoneyness ? 'Min moneyness must not exceed Max moneyness.'
      : [minDelta, maxDelta].some((v) => v != null && (v < 0 || v > 1)) ? 'Delta must be between 0 and 1.'
      : minDelta != null && maxDelta != null && minDelta > maxDelta ? 'Min delta must not exceed Max delta.'
      : null
    if (problem) {
      setError(problem)
      return
    }

    const request = { symbols, minDte, maxDte, minMoneyness, maxMoneyness, minDelta, maxDelta, strategy }
    setLoading(true)
    setError(null)
    try {
      const data = await screenOptions(request)
      setResult({ ...data, criteria: request })
      // A new scan replaces the rows a selection could refer to — cleared
      // here rather than whenever `result` changes, so restoring cached
      // results on remount keeps the user's selection.
      setSelected(new Map())
      setAnalyzeError(null)
    } catch (err) {
      setError(friendlyErrorMessage(err, err.message || 'Failed to run screener.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <div className="card">
        <form onSubmit={handleSubmit}>
          <div className="screener-fields">
            <div className="form-group screener-tickers">
              <label htmlFor="screener-tickers">
                Tickers
                <HelpTip label="About tickers">
                  Enter multiple tickers separated by a comma, e.g. AAPL, MSFT, NVDA. Up to 25 per scan;
                  futures roots like /ES work too.
                </HelpTip>
              </label>
              <input
                id="screener-tickers"
                className="input"
                value={criteria.tickers}
                onChange={update('tickers')}
                autoComplete="off"
              />
            </div>

            <div className="form-group screener-option-types">
              <label htmlFor="screener-option-type">
                Option Type
                <HelpTip label="About option types">
                  <strong>Short Puts / Short Calls:</strong> single contracts to sell (cash-secured put /
                  covered call), ranked by annualized ROI.
                  <br />
                  <strong>Long Puts / Long Calls:</strong> single contracts to buy, ranked by leverage (λ) —
                  roughly the option's % gain for a 1% move in the stock.
                  <br />
                  <strong>Multi-leg strategies</strong> (Put/Call Credit Spread through Ratio Call): the
                  Analyze page's Strategy Builder credit strategies, same names and rules — every combination
                  that opens for a net credit, with wings up to 5 strikes from their leg. A Jade Lizard's total
                  credit must also cover its call spread, so it has no upside risk.
                  <br />
                  For these, every leg must be inside the moneyness range (a straddle or iron butterfly needs
                  the range to include 0%), and the delta range applies to the legs you sell.
                </HelpTip>
              </label>
              <select
                id="screener-option-type"
                className="input"
                value={criteria.optionType}
                onChange={update('optionType')}
              >
                {strategies.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </div>

            <fieldset className="screener-range">
              <legend>
                Moneyness (% OTM)
                <HelpTip label="About moneyness">
                  Percent out-of-the-money from spot: below spot for puts, above spot for calls. 0 to 10 means
                  at-the-money out to 10% OTM. Use a negative minimum to include in-the-money strikes.
                </HelpTip>
              </legend>
              <div className="screener-range-inputs">
                <input type="number" step="0.5" className="input" aria-label="Min % OTM"
                  value={criteria.minMoneyness} onChange={update('minMoneyness')} />
                <span className="screener-range-sep">to</span>
                <input type="number" step="0.5" className="input" aria-label="Max % OTM"
                  value={criteria.maxMoneyness} onChange={update('maxMoneyness')} />
              </div>
            </fieldset>

            <fieldset className="screener-range">
              <legend>DTE</legend>
              <div className="screener-range-inputs">
                <input type="number" min="0" max="365" className="input" aria-label="Min DTE"
                  value={criteria.minDte} onChange={update('minDte')} />
                <span className="screener-range-sep">to</span>
                <input type="number" min="0" max="365" className="input" aria-label="Max DTE"
                  value={criteria.maxDte} onChange={update('maxDte')} />
              </div>
            </fieldset>

            <fieldset className="screener-range">
              <legend>
                Delta (optional)
                <HelpTip label="About delta">
                  Matched by absolute value, so 0.15 to 0.30 covers a −0.20 put and a 0.20 call. Leave either
                  bound blank for no limit on that side. Delta narrows the moneyness range rather than replacing
                  it, so keep moneyness wide enough to reach the deltas you want.
                </HelpTip>
              </legend>
              <div className="screener-range-inputs">
                <input type="number" min="0" max="1" step="0.01" className="input" aria-label="Min absolute delta"
                  placeholder="Any" value={criteria.minDelta} onChange={update('minDelta')} />
                <span className="screener-range-sep">to</span>
                <input type="number" min="0" max="1" step="0.01" className="input" aria-label="Max absolute delta"
                  placeholder="Any" value={criteria.maxDelta} onChange={update('maxDelta')} />
              </div>
            </fieldset>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? 'Scanning…' : 'Run Scan'}
            </button>
          </div>
        </form>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {result && !loading && (
        <>
          {result.errors.length > 0 && (
            <div className="alert warning">
              {result.errors.map((e) => (
                <div key={e.symbol}><strong>{e.symbol}</strong>: {e.message}</div>
              ))}
            </div>
          )}
          {result.truncated.length > 0 && (
            <div className="alert warning">
              {result.truncated.join(', ')}: too many contracts in this range, so only the strikes nearest
              the money were screened. Narrow the DTE or moneyness range to see them all.
            </div>
          )}

          <div className="card">
            <div className="section-header screener-results-header">
              <h3 className="section-title">
                {isMultiLeg(result.criteria?.strategy)
                  ? `Top ${strategyName(result.criteria.strategy)} Positions`
                  : LONG.includes(result.criteria?.strategy) ? 'Top Contracts to Buy' : 'Top Contracts to Sell'}
              </h3>
              <span className="summary-line">
                {result.results.length < result.totalMatches
                  ? `Top ${result.results.length} of ${result.totalMatches} matches`
                  : `${result.totalMatches} matches`}
              </span>
              <button
                type="button"
                className="btn btn-primary screener-analyze-selected"
                disabled={selected.size === 0}
                onClick={handleAnalyzeSelected}
              >
                Analyze Selected {selected.size > 0 ? `(${selected.size})` : ''}
              </button>
            </div>
            {analyzeError && <div className="alert error">{analyzeError}</div>}
            {result.results.length > 0 ? (
              <>
                <DataTable
                  // Remount per strategy so the default sort (leverage for
                  // long scans, annualized ROI otherwise) applies afresh.
                  key={result.criteria?.strategy ?? 'PUT'}
                  data={result.results}
                  columns={[
                    {
                      // Not a row field, so DataTable leaves it unsortable.
                      key: 'select',
                      label: '',
                      render: (r) => (
                        <input
                          type="checkbox"
                          checked={selected.has(r.symbol)}
                          onChange={() => toggleSelected(r)}
                          aria-label={`Select ${rowLabel(r)}`}
                        />
                      ),
                    },
                    ...(isMultiLeg(result.criteria?.strategy) ? STRATEGY_COLUMNS
                      : LONG.includes(result.criteria?.strategy) ? LONG_COLUMNS : COLUMNS),
                  ]}
                  defaultSortKey={LONG.includes(result.criteria?.strategy) ? 'leverage' : 'annualizedRoi'}
                  defaultSortDir="desc"
                  maxHeight="640px"
                />
                <p className="screener-hint">
                  {LONG.includes(result.criteria?.strategy)
                    ? 'Bought at the ask, so the max loss is the premium paid. Leverage (λ) = |delta| × spot ÷ ask: '
                      + 'roughly the option\'s % change for a 1% move in the stock. BE Move % is how far the stock '
                      + 'must move in your favor by expiration to break even.'
                    : isMultiLeg(result.criteria?.strategy)
                    ? 'Legs are priced at the bid when sold and the ask when bought; amounts are per share. ROI is '
                      + 'the P&L if the underlying is unchanged at expiration ÷ capital, where capital is the max '
                      + 'loss — or, when the upside risk is unlimited, the downside loss plus the spot price for '
                      + 'each uncovered short call (the shares that would cover it). Ann. ROI scales that to a '
                      + '365-day year.'
                    : 'ROI assumes you sell at the bid and the underlying is unchanged at expiration: (bid − '
                      + 'intrinsic) ÷ capital, where capital is the strike for a cash-secured put and the spot price '
                      + 'for a covered call. Ann. ROI scales that to a 365-day year.'}
                </p>
              </>
            ) : (
              <div className="alert warning">No contracts with a live quote matched these criteria.</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
