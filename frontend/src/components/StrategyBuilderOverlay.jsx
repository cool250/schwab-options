import { useEffect, useMemo, useState } from 'react'
import { getStrategyTemplates, buildStrategy, friendlyErrorMessage } from '../api/client'
import { getMultiplier } from '../utils/contractMultiplier'
import { formatOptionSymbol } from '../utils/optionSymbol'
import { formatDate } from '../utils/dateFormat'
import { createSessionCache } from '../utils/sessionCaches'
import HelpTip from './HelpTip'

/*
 * Strategy Builder — an overlay on the Analyze page, opened once a ticker is
 * loaded there. Pick Net Credit / Net Debit, a strategy template, how to
 * place each leg (delta, % OTM, expected move, strike, wing width), then
 * Build: the backend (service/strategy_builder.py) places the legs on the
 * live chain at mid prices and returns the best match plus alternatives.
 * "Apply" hands the chosen legs back to Analyze via onApply.
 *
 * The form is generated from GET /api/market/strategies, so a new template
 * there shows up here without frontend changes.
 */

// Template list and last-used choices — survive closing/reopening the
// overlay and leaving Analyze, cleared on sign-out like every page cache.
const builderCache = createSessionCache(() => ({
  templates: null,
  direction: 'credit',
  strategyId: null,
  paramsByStrategy: {},
  target: '',
  contracts: 1,
}))

const ANCHOR_MODE_LABELS = {
  atm: 'At the money',
  delta: 'Delta',
  otm_pct: 'Moneyness (% OTM)',
  sigma: 'Expected move (σ)',
  strike: 'Strike',
}
const WING_MODE_LABELS = {
  width: 'Width ($)',
  steps: 'Strike steps',
  delta: 'Delta',
  otm_pct: 'Moneyness (% OTM)',
}

// Deltas are entered as whole numbers ("16" for a 16Δ / 0.16 delta) — how
// traders actually say them; the API takes the fraction.
const toInput = (mode, value) => (value == null ? '' : mode === 'delta' ? String(+(value * 100).toFixed(2)) : String(value))
const fromInput = (mode, text) => {
  if (text === '' || text == null) return null
  const n = Number(text)
  if (!Number.isFinite(n)) return null
  return mode === 'delta' ? n / 100 : n
}

function defaultInputs(template) {
  const out = {}
  for (const leg of template.legs) {
    if (leg.role === 'same') continue
    out[leg.key] = { mode: leg.default.mode, text: toInput(leg.default.mode, leg.default.value) }
  }
  return out
}

function placementSummary(template, params) {
  const parts = []
  // Anchors first ("16Δ / $5 wing"), whatever order the legs are listed in.
  const ordered = [...template.legs].sort((a, b) => (a.role === 'wing') - (b.role === 'wing'))
  for (const leg of ordered) {
    const p = params[leg.key]
    if (!p) continue
    let text
    if (leg.role === 'anchor') {
      text = {
        atm: 'ATM',
        delta: `${+(p.value * 100).toFixed(1)}Δ`,
        otm_pct: `${p.value}% OTM`,
        sigma: `${p.value}σ`,
        strike: `$${p.value}`,
      }[p.mode]
    } else {
      text = {
        width: `$${p.value} wing`,
        steps: `${p.value}-strike wing`,
        delta: `${+(p.value * 100).toFixed(1)}Δ wing`,
        otm_pct: `${p.value}% OTM wing`,
      }[p.mode]
    }
    if (text && !parts.includes(text)) parts.push(text)
  }
  return parts.join(' / ')
}

const fmtUsd = (n) =>
  `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const fmtPrice = (n) => (Number.isFinite(n) ? n.toFixed(2) : '—')
const fmtPct = (n) => (Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '—')
// Screener convention: positive = out of the money, negative = in the money.
const fmtMoneyness = (n) =>
  !Number.isFinite(n) ? '—' : Math.abs(n) < 0.05 ? 'ATM' : `${Math.abs(n).toFixed(1)}% ${n > 0 ? 'OTM' : 'ITM'}`
const fmtDelta = (n) => (Number.isFinite(n) ? n.toFixed(2) : '—')
// Per-contract IV: a fraction from Tastytrade, a percentage from Schwab's
// chain (same inconsistency the Analyze chain table lives with).
const fmtIv = (n) => (Number.isFinite(n) ? `${(n > 3 ? n : n * 100).toFixed(1)}%` : '—')

/* Small payoff-shape sketch for a strategy card — illustrative only, with
   nominal strikes (anchors ±6 around 100, wings 6 or 3 further out) and a
   simple time-value curve, not real prices. */
function PayoffSketch({ template }) {
  const path = useMemo(() => {
    const strikes = {}
    for (const leg of template.legs) {
      if (leg.role !== 'anchor') continue
      const atm = leg.default.mode === 'atm' || (leg.default.mode === 'delta' && leg.default.value >= 0.45)
      strikes[leg.key] = atm ? 100 : leg.type === 'PUT' ? 94 : 106
    }
    for (const [a, b] of template.order || []) {
      if (!(strikes[a] < strikes[b])) strikes[a] = strikes[b] - 6
    }
    for (const leg of template.legs) {
      if (leg.role === 'same') strikes[leg.key] = strikes[leg.of]
    }
    for (const leg of template.legs) {
      if (leg.role === 'wing') strikes[leg.key] = strikes[leg.of] + leg.dir * (leg.default.mode === 'steps' ? 3 : 6)
    }
    const intrinsic = (type, k, s) => (type === 'PUT' ? Math.max(k - s, 0) : Math.max(s - k, 0))
    const premium = (type, k) => intrinsic(type, k, 100) + 5 * Math.exp(-Math.abs(k - 100) / 12)
    const credit = template.legs.reduce((sum, l) => sum - l.qty * premium(l.type, strikes[l.key]), 0)
    const pl = (s) => credit + template.legs.reduce((sum, l) => sum + l.qty * intrinsic(l.type, strikes[l.key], s), 0)
    const xs = Array.from({ length: 61 }, (_, i) => 76 + i * 0.8)
    const ys = xs.map(pl)
    const lo = Math.min(...ys, 0)
    const hi = Math.max(...ys, 0)
    const scaleY = (y) => 44 - ((y - lo) / (hi - lo || 1)) * 40
    return {
      d: xs.map((x, i) => `${i ? 'L' : 'M'}${((x - 76) * 2.5).toFixed(1)},${scaleY(ys[i]).toFixed(1)}`).join(' '),
      zero: scaleY(0),
    }
  }, [template])
  return (
    <svg className="sb-sketch" viewBox="0 0 120 48" aria-hidden="true" preserveAspectRatio="none">
      <line x1="0" x2="120" y1={path.zero} y2={path.zero} className="sb-sketch-zero" />
      <path d={path.d} className="sb-sketch-line" />
    </svg>
  )
}

export default function StrategyBuilderOverlay({ symbol, spot, expirations, initialExpIndex, hasLegs, onApply, onClose }) {
  const [templates, setTemplates] = useState(builderCache.templates)
  const [loadError, setLoadError] = useState(null)
  const [direction, setDirection] = useState(builderCache.direction)
  const [strategyId, setStrategyId] = useState(builderCache.strategyId)
  const [paramsByStrategy, setParamsByStrategy] = useState(builderCache.paramsByStrategy)
  const [target, setTarget] = useState(builderCache.target)
  const [contracts, setContracts] = useState(builderCache.contracts)
  const [expIndex, setExpIndex] = useState(Math.min(initialExpIndex ?? 0, Math.max(expirations.length - 1, 0)))
  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState(null)
  const [result, setResult] = useState(null)
  const [choice, setChoice] = useState(0) // 0 = best, n = alternatives[n - 1]

  useEffect(() => {
    if (templates) return
    let cancelled = false
    getStrategyTemplates()
      .then((list) => {
        if (cancelled) return
        builderCache.templates = list
        setTemplates(list)
      })
      .catch((e) => !cancelled && setLoadError(friendlyErrorMessage(e, e.message || 'Failed to load strategies.')))
    return () => {
      cancelled = true
    }
  }, [templates])

  useEffect(() => {
    Object.assign(builderCache, { direction, strategyId, paramsByStrategy, target, contracts })
  }, [direction, strategyId, paramsByStrategy, target, contracts])

  // Esc closes; the page behind doesn't scroll while the overlay is open.
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

  const visible = (templates || []).filter((t) => t.direction === direction)
  const template = visible.find((t) => t.id === strategyId) || null
  const inputs = template ? paramsByStrategy[template.id] || defaultInputs(template) : null
  const isCredit = direction === 'credit'
  const multiplier = getMultiplier(symbol)
  const qty = Math.max(1, Math.floor(Number(contracts) || 1))
  const scale = multiplier * qty
  const exp = expirations[expIndex]

  const clearResult = () => {
    setResult(null)
    setBuildError(null)
    setChoice(0)
  }

  const pickDirection = (d) => {
    if (d === direction) return
    setDirection(d)
    setStrategyId(null)
    clearResult()
  }

  const pickStrategy = (id) => {
    setStrategyId(id)
    clearResult()
  }

  const setLegInput = (key, patch) => {
    setParamsByStrategy((prev) => ({
      ...prev,
      [template.id]: { ...inputs, [key]: { ...inputs[key], ...patch } },
    }))
    clearResult()
  }

  const resetDefaults = () => {
    setParamsByStrategy((prev) => {
      const next = { ...prev }
      delete next[template.id]
      return next
    })
    clearResult()
  }

  const build = async (e) => {
    e?.preventDefault()
    if (!template || !exp) return
    const params = {}
    for (const [key, { mode, text }] of Object.entries(inputs)) {
      params[key] = { mode, value: mode === 'atm' ? null : fromInput(mode, text) }
    }
    const targetValue = target === '' ? null : Number(target)
    setBuilding(true)
    setBuildError(null)
    setResult(null)
    setChoice(0)
    try {
      const res = await buildStrategy({
        symbol,
        dte: exp.dte,
        expirationDate: exp.date,
        strategy: template.id,
        params,
        target: Number.isFinite(targetValue) ? targetValue : null,
      })
      setResult(res)
    } catch (err) {
      setBuildError(friendlyErrorMessage(err, err.message || 'Failed to build the strategy.'))
    } finally {
      setBuilding(false)
    }
  }

  const candidates = result?.best ? [result.best, ...result.alternatives] : []
  const chosen = candidates[choice] || null

  const apply = () => {
    if (!chosen) return
    const premium = chosen.netPremium
    onApply({
      expirationDate: result.expirationDate,
      dte: result.dte,
      legs: chosen.legs.map((l) => ({
        side: l.qty < 0 ? 'SELL' : 'BUY',
        qty: Math.abs(l.qty) * qty,
        type: l.type,
        strike: l.strike,
        premium: +l.mid.toFixed(2),
      })),
      label: [
        template.name,
        placementSummary(template, result.params),
        `${fmtUsd(premium)} ${premium >= 0 ? 'credit' : 'debit'}`,
      ]
        .filter(Boolean)
        .join(' · '),
    })
  }

  return (
    <div className="sb-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sb-dialog" role="dialog" aria-modal="true" aria-labelledby="sb-title">
        <div className="sb-header">
          <div>
            <h2 className="sb-title" id="sb-title">Build Strategy</h2>
            <span className="text-muted">
              {symbol} · ${Number(spot || 0).toFixed(2)}
            </span>
          </div>
          <button type="button" className="sb-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="tab-row sb-direction">
          {[
            { id: 'credit', label: 'Net Credit' },
            { id: 'debit', label: 'Net Debit' },
          ].map((d) => (
            <button
              key={d.id}
              type="button"
              className={`tab-item ${direction === d.id ? 'active' : ''}`}
              onClick={() => pickDirection(d.id)}
            >
              {d.label}
            </button>
          ))}
        </div>

        {loadError && <div className="alert error">{loadError}</div>}
        {!templates && !loadError && <p className="text-muted">Loading strategies…</p>}

        <div className="sb-cards">
          {visible.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`sb-card ${t.id === strategyId ? 'active' : ''}`}
              onClick={() => pickStrategy(t.id)}
              title={t.description}
            >
              <PayoffSketch template={t} />
              <span className="sb-card-name">{t.name}</span>
            </button>
          ))}
        </div>

        {template && (
          <form className="sb-form" onSubmit={build}>
            <p className="sb-description">{template.description}</p>

            <div className="sb-grid">
              <div className="form-group">
                <label htmlFor="sb-exp">Expiration</label>
                <select
                  id="sb-exp"
                  className="input"
                  value={expIndex}
                  onChange={(e) => {
                    setExpIndex(+e.target.value)
                    clearResult()
                  }}
                >
                  {expirations.map((x, i) => (
                    <option key={x.date} value={i}>
                      {formatDate(x.date)} · {x.dte}d
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="sb-contracts">Contracts</label>
                <input
                  id="sb-contracts"
                  className="input"
                  type="number"
                  min="1"
                  step="1"
                  value={contracts}
                  onChange={(e) => setContracts(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label htmlFor="sb-target">
                  {isCredit ? 'Min credit' : 'Max debit'}
                  <HelpTip label="About the premium target">
                    Optional, per share at mid prices (e.g. 1.50 = $150 per contract on a 100-share option). If the
                    legs placed from your parameters miss it, nearby strikes (up to 5 either way) are searched for the
                    closest combination that {isCredit ? 'collects at least' : 'costs at most'} this much.
                  </HelpTip>
                </label>
                <input
                  id="sb-target"
                  className="input"
                  type="number"
                  min="0"
                  step="0.05"
                  placeholder="Any"
                  value={target}
                  onChange={(e) => {
                    setTarget(e.target.value)
                    clearResult()
                  }}
                />
              </div>
            </div>

            <div className="sb-legs-form">
              {template.legs
                .filter((leg) => leg.role !== 'same')
                .map((leg) => {
                  const input = inputs[leg.key]
                  const labels = leg.role === 'anchor' ? ANCHOR_MODE_LABELS : WING_MODE_LABELS
                  return (
                    <div key={leg.key} className="sb-leg-row">
                      <span className="sb-leg-label">
                        <span className={`sb-side ${leg.qty < 0 ? 'sell' : 'buy'}`}>{leg.qty < 0 ? 'Sell' : 'Buy'}</span>
                        {leg.label}
                        {template.legs
                          .filter((s) => s.role === 'same' && s.of === leg.key)
                          .map((s) => (
                            <span key={s.key} className="text-muted"> + {s.type.toLowerCase()} at the same strike</span>
                          ))}
                      </span>
                      <select
                        className="input"
                        aria-label={`${leg.label} placement`}
                        value={input.mode}
                        onChange={(e) => {
                          const mode = e.target.value
                          const def = leg.default.mode === mode ? toInput(mode, leg.default.value) : ''
                          setLegInput(leg.key, { mode, text: def })
                        }}
                      >
                        {(leg.role === 'anchor' ? template.anchorModes : template.wingModes).map((m) => (
                          <option key={m} value={m}>
                            {labels[m]}
                          </option>
                        ))}
                      </select>
                      {input.mode === 'atm' ? (
                        <span className="text-muted sb-leg-value">Nearest strike to ${Number(spot || 0).toFixed(2)}</span>
                      ) : (
                        <input
                          className="input sb-leg-value"
                          type="number"
                          step="any"
                          aria-label={`${leg.label} ${labels[input.mode]}`}
                          placeholder={
                            { delta: 'e.g. 16', otm_pct: 'e.g. 5', sigma: 'e.g. 1', strike: 'e.g. 450', width: 'e.g. 5', steps: 'e.g. 1' }[
                              input.mode
                            ]
                          }
                          value={input.text}
                          onChange={(e) => setLegInput(leg.key, { text: e.target.value })}
                        />
                      )}
                    </div>
                  )
                })}
            </div>

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={building || !exp}>
                {building ? 'Building…' : 'Build'}
              </button>
              <button type="button" className="btn btn-secondary" onClick={resetDefaults} disabled={building}>
                Reset to defaults
              </button>
              <span className="text-muted sb-hint">Priced at mid · deltas as whole numbers (16 = 0.16)</span>
            </div>
          </form>
        )}

        {buildError && <div className="alert error">{buildError}</div>}

        {result && (
          <div className="sb-result">
            {result.reasons.length > 0 && (
              <div className={`alert ${result.best ? 'warning' : 'error'}`}>
                {result.reasons.map((r) => (
                  <div key={r}>{r}</div>
                ))}
              </div>
            )}

            {chosen && (
              <>
                <div className="metrics-row sb-metrics">
                  <div className="metric">
                    <span className="metric-label">{chosen.netPremium >= 0 ? 'Net Credit' : 'Net Debit'}</span>
                    <span className={`metric-value ${chosen.netPremium >= 0 ? 'positive' : 'negative'}`}>
                      {fmtUsd(chosen.netPremium * scale)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Max Profit</span>
                    <span className="metric-value positive">
                      {chosen.maxProfit == null ? 'Unlimited' : fmtUsd(chosen.maxProfit * scale)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Max Loss</span>
                    <span className="metric-value negative">
                      {chosen.maxLoss == null ? 'Unlimited' : fmtUsd(Math.min(chosen.maxLoss, 0) * scale)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Breakeven</span>
                    <span className="metric-value highlight">
                      {chosen.breakevens.length ? chosen.breakevens.map((b) => `$${b.toFixed(2)}`).join(' / ') : '—'}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">
                      POP (est.)
                      <HelpTip label="About probability of profit">
                        Chance of finishing above zero P&L at expiration, from a lognormal model at the chain's ATM
                        implied volatility ({fmtPct(result.iv)}). An estimate: no skew, no early exit.
                      </HelpTip>
                    </span>
                    <span className="metric-value">{fmtPct(chosen.pop)}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">{isCredit ? 'Return on Risk' : 'Reward / Risk'}</span>
                    <span className="metric-value">
                      {chosen.returnOnRisk == null
                        ? '—'
                        : isCredit
                          ? fmtPct(chosen.returnOnRisk)
                          : `${chosen.returnOnRisk.toFixed(2)}×`}
                    </span>
                  </div>
                </div>

                <div className="sb-table-wrap">
                  <table className="data-table sb-table">
                    <thead>
                      <tr>
                        <th>Side</th>
                        <th>Contract</th>
                        <th>Moneyness</th>
                        <th>Delta</th>
                        <th>IV</th>
                        <th>Bid</th>
                        <th>Ask</th>
                        <th>Mid</th>
                      </tr>
                    </thead>
                    <tbody>
                      {chosen.legs.map((l) => (
                        <tr key={l.key}>
                          <td>
                            <span className={`sb-side ${l.qty < 0 ? 'sell' : 'buy'}`}>
                              {l.qty < 0 ? 'Sell' : 'Buy'} {Math.abs(l.qty) * qty}
                            </span>
                          </td>
                          <td>{formatOptionSymbol(symbol, result.expirationDate, l.strike, l.type) || l.symbol}</td>
                          <td>{fmtMoneyness(l.otmPct)}</td>
                          <td>{fmtDelta(l.delta)}</td>
                          <td>{fmtIv(l.iv)}</td>
                          <td>{fmtPrice(l.bid)}</td>
                          <td>{fmtPrice(l.ask)}</td>
                          <td>{fmtPrice(l.mid)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {candidates.length > 1 && (
                  <div className="sb-alternatives">
                    <span className="metric-label">Alternatives</span>
                    <div className="sb-alt-list">
                      {candidates.map((c, i) => (
                        <button
                          key={c.legs.map((l) => l.symbol).join('|')}
                          type="button"
                          className={`sb-alt ${i === choice ? 'active' : ''}`}
                          onClick={() => setChoice(i)}
                        >
                          <span className="sb-alt-strikes">
                            {c.legs.map((l) => `${l.strike}${l.type === 'PUT' ? 'P' : 'C'}`).join(' / ')}
                          </span>
                          <span className={c.netPremium >= 0 ? 'positive' : 'negative'}>
                            {fmtUsd(c.netPremium)} {c.netPremium >= 0 ? 'cr' : 'db'}
                          </span>
                          <span className="text-muted">POP {fmtPct(c.pop)}</span>
                          {i === 0 && <span className="sb-alt-tag">Best match</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="form-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={apply}
                    title={hasLegs ? 'Replaces the legs currently on Analyze' : undefined}
                  >
                    Apply
                  </button>
                  <span className="text-muted sb-hint">
                    {formatDate(result.expirationDate)} · {result.dte}d · spot ${Number(result.spot).toFixed(2)}
                  </span>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
