import { useMemo } from 'react'
import { taxSummary, incomeExpenseGroups } from '../utils/taxSummary'
import { usd, signClass } from '../utils/reportStats'

/*
 * Reports' Tax summary tab: the year's realized P&L split the way the tax
 * forms split it — Section 1256 contracts (Form 6781, 60/40 and marked to
 * market at year end) apart from everything else (Form 8949 / Schedule D,
 * short- or long-term by holding period) — by estimated-tax period, and the
 * year's interest, dividends and fees grouped by how a return treats them.
 * A check against the 1099-B, not a replacement for it. The math is
 * taxSummary() and incomeExpenseGroups() in utils/taxSummary.js.
 */

function Money({ v, strong }) {
  const text = usd(v)
  return <td className={`num ${signClass(v)}`}>{strong ? <strong>{text}</strong> : text}</td>
}

/**
 * optionTrades / equityTrades: the year's closed trades. unrealized: the YTD
 * view's open-positions load ({ loading, data, failed }) for the current
 * year, else null. incomeFees: the year's dividends, interest and fees
 * ({ fees, incomeBy, feesBy } — Reports' incomeFeeTotals), or null.
 * year / isCurrentYear / lastMonth: the period shown.
 */
export default function TaxSummary({ optionTrades, equityTrades, unrealized, incomeFees, year, isCurrentYear, lastMonth }) {
  const data = unrealized?.data
  const openKnown = isCurrentYear && data && !data.futuresMissing
  const open1256 = openKnown ? data.futures + data.futuresOptions : null
  const t = useMemo(
    () => taxSummary({ optionTrades, equityTrades, open1256, lastMonth }),
    [optionTrades, equityTrades, open1256, lastMonth],
  )
  const { s1256, other, periods } = t
  const fees = incomeFees?.fees ?? null
  const groups = useMemo(() => incomeFees && incomeExpenseGroups(incomeFees.incomeBy, incomeFees.feesBy), [incomeFees])

  const openCell = !isCurrentYear ? <td className="num">See 1099-B</td>
    : unrealized?.loading ? <td className="num">Loading…</td>
    : open1256 == null ? <td className="num">Unavailable</td>
    : <Money v={open1256} />

  const tiles = [
    {
      label: 'Section 1256',
      value: usd(s1256.total),
      sub: <>60% long-term {usd(s1256.longTerm)}<span className="report-kpi-subline">40% short-term {usd(s1256.shortTerm)}</span></>,
      hero: true,
    },
    { label: 'Short-term', value: usd(other.shortTerm), sub: 'Equity options and shares' },
    { label: 'Long-term', value: usd(other.longTerm), sub: 'Held more than a year' },
    {
      label: 'Total',
      value: usd(s1256.total + other.shortTerm + other.longTerm),
      sub: isCurrentYear && open1256 != null ? '1256 marked at today’s prices' : 'Realized',
    },
  ]

  return (
    <>
      <div className="card">
        <div className="report-kpis report-kpis--all">
          {tiles.map((k) => (
            <div key={k.label} className={`report-kpi${k.hero ? ' report-kpi--hero' : ''}`}>
              <span className="report-kpi-label">{k.label}</span>
              <span className="report-kpi-value">{k.value}</span>
              <span className="report-kpi-sub">{k.sub}</span>
            </div>
          ))}
        </div>
        <p className="report-footnote">
          Before commissions and fees{fees ? <> ({usd(fees)} in {year})</> : null}, which the 1099-B folds into
          proceeds and cost. An estimate to check your 1099-B against — your tax adviser decides what you report.
        </p>
      </div>

      <div className="report-row">
        <div className="card">
          <div className="report-card-head">
            <h3 className="section-title">Section 1256 contracts</h3>
            <span className="report-card-note">Form 6781 · 60% long-term, 40% short-term</span>
          </div>
          <div className="report-table-wrap">
            <table className="report-table tax-table">
              <tbody>
                <tr><td>Futures options, realized</td><Money v={s1256.futuresOptions} /></tr>
                <tr><td>Futures, realized</td><Money v={s1256.futures} /></tr>
                {s1256.indexOptions !== 0 && <tr><td>Index options, realized</td><Money v={s1256.indexOptions} /></tr>}
                <tr>
                  <td>Open positions, marked to market</td>
                  {openCell}
                </tr>
              </tbody>
              <tfoot>
                <tr><td>Total</td><Money v={s1256.total} /></tr>
                <tr><td>60% long-term</td><Money v={s1256.longTerm} /></tr>
                <tr><td>40% short-term</td><Money v={s1256.shortTerm} /></tr>
              </tfoot>
            </table>
          </div>
          <p className="report-footnote">
            {isCurrentYear
              ? 'Open futures and futures options count at their value on Dec 31; shown at today’s prices until then. '
              : 'The open positions’ year-end value is box 10 of the 1099-B. '}
            Positions carried in from last year were already marked at last year&apos;s close (box 9) — that
            adjustment isn&apos;t included here.
          </p>
        </div>

        <div className="card">
          <div className="report-card-head">
            <h3 className="section-title">Other trades</h3>
            <span className="report-card-note">Form 8949 / Schedule D</span>
          </div>
          <div className="report-table-wrap">
            <table className="report-table tax-table">
              <thead>
                <tr><th /><th className="num">Short-term</th><th className="num">Long-term</th><th className="num">Total</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Equity options</td>
                  <Money v={other.equityOptions.short} /><Money v={other.equityOptions.long} />
                  <Money v={other.equityOptions.short + other.equityOptions.long} />
                </tr>
                <tr>
                  <td>Stock &amp; ETF</td>
                  <Money v={other.stocks.short} /><Money v={other.stocks.long} />
                  <Money v={other.stocks.short + other.stocks.long} />
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td>Total</td>
                  <Money v={other.shortTerm} /><Money v={other.longTerm} /><Money v={other.shortTerm + other.longTerm} />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="report-footnote">
            A written option is short-term however long it was open. An assigned option&apos;s premium is counted
            here when assigned; for tax it adjusts the shares&apos; cost (a put) or sale price (a call) instead.
            Wash sales aren&apos;t applied.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="report-card-head">
          <h3 className="section-title">By estimated-tax period</h3>
          <span className="report-card-note">Realized gains in each Form 1040-ES period</span>
        </div>
        <div className="report-table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                <th>Period</th>
                <th>Payment due</th>
                {['Section 1256', 'Short-term', 'Long-term', 'Total'].map((h) => <th key={h} className="num">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => (
                <tr key={p.label}>
                  <td className="report-sym">{p.label}</td>
                  <td>{p.due}{p.due === 'Jan 15' ? `, ${year + 1}` : ''}</td>
                  <Money v={p.s1256} /><Money v={p.shortTerm} /><Money v={p.longTerm} /><Money v={p.total} strong />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="report-footnote">
          Uneven periods on purpose: they&apos;re the ones the annualized-income method (Form 2210, Schedule AI)
          uses, which lowers early payments when gains come late in the year. Open 1256 positions count in the last period.
        </p>
      </div>
      <div className="card">
        <div className="report-card-head">
          <h3 className="section-title">Expenses and income</h3>
          <span className="report-card-note">From your Schwab activity in {year}</span>
        </div>
        {!groups ? (
          <p className="summary-line">Interest, dividends and fees couldn&apos;t be loaded.</p>
        ) : (
          <div className="report-table-wrap">
            <table className="report-table tax-table">
              {[
                { key: 'deductible', title: 'Deductible expenses', note: 'Schedule C with trader tax status; otherwise investment interest (Form 4952, if you itemize)' },
                { key: 'inBasis', title: 'Already in your trade results', note: 'In the 1099-B’s proceeds and cost — not deducted again' },
                { key: 'income', title: 'Income', note: '1099-INT / 1099-DIV' },
              ].map((g) => (
                <tbody key={g.key}>
                  <tr className="tax-group-head">
                    <td>{g.title}<span className="tax-group-note">{g.note}</span></td>
                    <td className="num">{usd(groups[g.key].total)}</td>
                  </tr>
                  {groups[g.key].items.map((l) => (
                    <tr key={l.label}><td className="tax-line">{l.label}</td><td className="num">{usd(l.amount)}</td></tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        )}
        <p className="report-footnote">
          Other trading costs — data feeds, software, equipment, a home office — aren&apos;t in your Schwab activity;
          with trader tax status they&apos;re Schedule C expenses too. Without it, investment expenses other than
          interest aren&apos;t deductible.
        </p>
      </div>
    </>
  )
}
