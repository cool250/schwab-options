// Display formatting for numbers the API returns as plain numbers (see
// service/portfolio/models.py). Missing values render as "—", never "$0".

export function money(value, decimals = 2) {
  if (value == null || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return `${value < 0 ? '-' : ''}$${abs}`
}

export function count(value) {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}
