// Backend dates arrive as "YYYY-MM-DD" strings — displayed everywhere as
// MM/DD/YYYY instead. Parsed by splitting rather than `new Date(str)` to
// avoid UTC-vs-local timezone shift landing on the wrong day.
export function formatDate(dateStr) {
  if (!dateStr) return dateStr
  const parts = dateStr.split('-')
  if (parts.length !== 3) return dateStr
  const [year, month, day] = parts
  return `${month}/${day}/${year}`
}
