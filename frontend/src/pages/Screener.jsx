import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { screenOptions, friendlyErrorMessage } from '../api/client'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { formatDate } from '../utils/dateFormat'
import { setCopilotContext, clearCopilotContext } from '../utils/copilotContext'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'
import HelpTip from '../components/HelpTip'

// Survives navigating away and back within a session (same pattern as
// strikeLabCache in StrikeLab.jsx) — a screen across several tickers takes
// a few seconds, so losing it on a quick detour to another page would hurt.
const DEFAULT_CRITERIA = {
  tickers: 'AAPL, MSFT, AMZN, NVDA',
  minMoneyness: 0,
  maxMoneyness: 10,
  minDte: 0,
  maxDte: 45,
  minDelta: '',
  maxDelta: '',
  puts: true,
  calls: true,
}

const screenerCache = {
  criteria: DEFAULT_CRITERIA,
  result: null,
}

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
const int = (v) => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }))

// Same router-state handoff as Positions' "Analyze Selected" (StrikeLab
// reads location.state.analyzePositions on mount): each selected contract
// arrives as a 1-lot short leg — negative quantity = sold — priced at the
// bid, the same premium the ROI columns assume.
function toAnalyzePosition(row) {
  return {
    symbol: row.underlying,
    strike: row.strike,
    optionType: row.type,
    quantity: -1,
    premium: row.bid,
    dte: row.dte,
    ticker: row.underlying,
    expirationDate: row.expirationDate,
  }
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

export default function Screener() {
  const navigate = useNavigate()
  // Defaults first, so a field added since the cached criteria were saved
  // starts at its default instead of undefined.
  const [criteria, setCriteria] = useState(() => ({ ...DEFAULT_CRITERIA, ...screenerCache.criteria }))
  const [result, setResult] = useState(screenerCache.result)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  // Selected result rows, keyed by contract symbol (unique per row).
  const [selected, setSelected] = useState(new Map())
  const [analyzeError, setAnalyzeError] = useState(null)

  useEffect(() => {
    screenerCache.criteria = criteria
  }, [criteria])

  useEffect(() => {
    screenerCache.result = result
    // A new screen replaces the rows a selection could refer to.
    setSelected(new Map())
    setAnalyzeError(null)
  }, [result])

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
  // call on the same ticker/expiration (e.g. a short strangle) is fine.
  function handleAnalyzeSelected() {
    const rows = Array.from(selected.values())
    const tickers = new Set(rows.map((r) => r.underlying))
    const expirations = new Set(rows.map((r) => r.expirationDate))
    if (tickers.size > 1 || expirations.size > 1) {
      setAnalyzeError('Select options for a single ticker and expiration date to analyze together.')
      return
    }
    setAnalyzeError(null)
    navigate('/analyze', { state: { analyzePositions: rows.map(toAnalyzePosition), view: 'graph' } })
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
      topResults: result.results.slice(0, 20).map((r) => ({
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
      })),
    })
    return () => clearCopilotContext('Screener')
  }, [result])

  const update = (field) => (e) =>
    setCriteria((c) => ({ ...c, [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    const symbols = parseTickers(criteria.tickers)
    const optionTypes = [criteria.puts && 'PUT', criteria.calls && 'CALL'].filter(Boolean)
    const minDte = Number(criteria.minDte)
    const maxDte = Number(criteria.maxDte)
    const minMoneyness = optionalNumber(criteria.minMoneyness)
    const maxMoneyness = optionalNumber(criteria.maxMoneyness)
    const minDelta = optionalNumber(criteria.minDelta)
    const maxDelta = optionalNumber(criteria.maxDelta)

    const problem =
      symbols.length === 0 ? 'Enter at least one ticker.'
      : symbols.length > 25 ? 'Screen at most 25 tickers at a time.'
      : optionTypes.length === 0 ? 'Select Put, Call, or both.'
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

    const request = { symbols, minDte, maxDte, minMoneyness, maxMoneyness, minDelta, maxDelta, optionTypes }
    setLoading(true)
    setError(null)
    try {
      const data = await screenOptions(request)
      setResult({ ...data, criteria: request })
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
          <div className="screener-top-row">
            <div className="form-group screener-tickers">
              <label htmlFor="screener-tickers">Tickers</label>
              <input
                id="screener-tickers"
                className="input"
                value={criteria.tickers}
                onChange={update('tickers')}
                placeholder="AAPL, MSFT, /ES"
                autoComplete="off"
              />
            </div>

            <fieldset className="screener-range screener-option-types">
              <legend>Option Type</legend>
              <div className="screener-option-type-inputs">
                <label className="toggle-label">
                  <input type="checkbox" className="toggle-checkbox" checked={criteria.puts} onChange={update('puts')} />
                  <span>Puts</span>
                </label>
                <label className="toggle-label">
                  <input type="checkbox" className="toggle-checkbox" checked={criteria.calls} onChange={update('calls')} />
                  <span>Calls</span>
                </label>
              </div>
            </fieldset>
          </div>

          <div className="screener-ranges">
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
              <legend>DTE (days)</legend>
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
                Delta (absolute) · optional
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
              <h3 className="section-title">Top Contracts to Sell</h3>
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
                          aria-label={`Select ${formatOptionSymbol(r.underlying, r.expirationDate, r.strike, r.type) ?? r.symbol}`}
                        />
                      ),
                    },
                    ...COLUMNS,
                  ]}
                  defaultSortKey="annualizedRoi"
                  defaultSortDir="desc"
                  maxHeight="640px"
                />
                <p className="screener-hint">
                  ROI assumes you sell at the bid and the underlying is unchanged at expiration: (bid − intrinsic)
                  ÷ capital, where capital is the strike for a cash-secured put and the spot price for a covered
                  call. Ann. ROI scales that to a 365-day year.
                </p>
              </>
            ) : (
              <div className="alert warning">No contracts with a live bid matched these criteria.</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
