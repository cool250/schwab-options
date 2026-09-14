# Strangle

Two-legged, same-expiration strategy that bets on the *magnitude* of a move
rather than its direction — different, further-OTM strikes for the call
and put — and can be run long (buying volatility) or short (selling
volatility).

**Long (buy both legs):** profits from a large move in either direction —
common ahead of a known binary catalyst (earnings, FDA decision) where the
direction is uncertain but a big move is expected. Max loss is the total
premium paid, if the stock sits still through expiration. Net vega-positive
and theta-negative — this is a bet that realized volatility (or IV
expansion) outpaces time decay, so it loses value on quiet days even if the
outlook is eventually right.

**Short (sell both legs) — only ever as a *covered* strangle, never
naked.** A naked short call has genuinely uncapped upside risk — worse than
a naked short put, which is at least bounded at the stock going to zero —
so this strategy is only suggested when there's an existing open position
that lets the call leg actually be covered:
- **Check for a covering position first, before suggesting this at all.**
  Pull `get_stock_positions` (or `get_futures_positions` for a futures
  underlying) — the call leg needs at least 100 shares (or one long futures
  contract) already held per short call sold. If there's no such position,
  don't recommend a short strangle; say plainly that it isn't appropriate
  without an existing covering position, and suggest a covered call alone
  or a cash-secured put instead.
- **With the call covered, the risk profile is** a covered call on the
  upside (capped gain above the call strike — the shares would get called
  away — not unlimited loss) **plus** a cash-secured/naked put below the put
  strike (same bounded-at-zero risk as a CSP). Collects two premiums
  instead of one against the same underlying shares, in exchange for taking
  on the CSP-style put-side risk in addition to the covered call's own
  opportunity-cost risk (missing further upside past the call strike).
- Profits if the stock stays between the two strikes through expiration,
  collecting both premiums; a big move past either strike still means
  giving up further upside (call side, capped) or taking on more downside
  exposure (put side, same as a CSP), so this is still a range-bound bet,
  just one whose worst case is now defined instead of uncapped.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte` (the
expiration pill the user already has open on StrikeLab), search that
expiration — don't call `get_expirations` and choose a different one, and
don't ask the user which expiration they want, since it's already right in
front of them. Only fall back to asking or picking one yourself when no
page context is present.

**Strike selection for the covered version:** favor **0.30 delta or lower**
on each leg — same reasoning as a CSP, a lower delta on either side trades
some premium for a better chance that side expires worthless. Pull
`get_price_history` for the underlying and use the support level for the
put strike and the resistance level for the call strike, the same way a CSP
uses support alone — a level the stock has actually respected before is a
more specific signal than delta alone, and if the ≤0.30-delta strike and
the nearest support/resistance don't line up closely, say so rather than
picking one arbitrarily.

**When each fits:** long version ahead of a known volatility catalyst with
an uncertain direction; the covered short version as a range-bound income
bet on shares (or a futures position) already held, collecting extra
premium on top of what a covered call or CSP alone would.
