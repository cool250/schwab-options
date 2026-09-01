// Standard equity/index option contract multiplier (100 shares/contract).
export const MULTIPLIER = 100

// Futures options settle on the underlying future's own point value, not the
// standard 100-share equity multiplier — e.g. an ES option is $50/point, NQ
// is $20/point. Keyed by root symbol with the leading '/' stripped.
// Must mirror TransactionService._CONTRACT_MULTIPLIER in service/transactions.py.
export const FUTURES_MULTIPLIER_BY_ROOT = { ES: 50, NQ: 20, RTY: 50 }

export function getMultiplier(sym) {
  if (!sym) return MULTIPLIER
  const root = sym.replace(/^\//, '').toUpperCase()
  return FUTURES_MULTIPLIER_BY_ROOT[root] ?? MULTIPLIER
}
