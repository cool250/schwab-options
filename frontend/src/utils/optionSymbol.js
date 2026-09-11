import { formatDate } from './dateFormat'

// Shared "clean" option symbol format used on every page that displays an
// option contract — e.g. "SPY 09/04/2026 756.00 P" — instead of each page
// parsing/formatting the raw OCC-style contract symbol (e.g.
// "SPY   260904P00756000") its own way.
//
// Built from structured fields rather than the raw symbol string, since the
// raw symbol's layout differs between equity and futures-option contracts
// but the structured fields (ticker, expiration, strike, put/call) don't.
//
// Returns null (rather than guessing) when there's no single strike to show
// — e.g. a grouped ratio-spread row, which has two strikes (see
// long_leg/short_leg) and doesn't fit this one-strike template. Callers
// should fall back to the row's own `symbol` in that case.
export function formatOptionSymbol(ticker, expirationDate, strike, optionType) {
  if (!ticker || !expirationDate || strike == null || !Number.isFinite(strike)) return null
  const cp = optionType === 'PUT' ? 'P' : 'C'
  return `${ticker} ${formatDate(expirationDate)} ${strike.toFixed(2)} ${cp}`
}
