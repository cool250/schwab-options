# Straddle

Two-legged, same-expiration strategy: a put and a call at the **same
strike**, usually at the money. It's the at-the-money version of a strangle
(see strangle.md): more premium and a narrower profit zone. Like the
strangle, it can be run long (buying volatility) or short (selling
volatility).

**Long (buy both legs) — net debit.** Profits if the stock moves more than
the total premium paid in either direction by expiration. Breakevens:
`strike ± total_debit`. Max loss is the debit, if the stock pins the strike.
It is strongly theta-negative: this is a bet that the realized move (or an
IV expansion) beats the premium, typically ahead of a binary catalyst. It is
inherently a debit strategy, so present it only when the user asks for a
long-volatility trade, and don't dress it up as a credit. `build_strategy`
doesn't build debit strategies for the copilot, so take its strikes and
prices from `get_option_chain`.

**Short (sell both legs) — only ever as a *covered* straddle, never naked.**
The short call has uncapped upside risk, so the same rule as the short
strangle applies:
- **Check for a covering position first.** Pull `get_stock_positions` (or
  `get_futures_positions` for a futures underlying). The call leg needs at
  least 100 shares (or one long futures contract) held per short call. If
  there's no such position, don't recommend a short straddle. Say plainly
  that it isn't appropriate without one, and suggest an iron butterfly
  instead (see iron_butterfly.md). That is the same short straddle with
  defined risk on both sides.
- **With the call covered,** the upside works like a covered call written at
  the money (shares called away above the strike). The downside works like
  a cash-secured put at the money, with assignment as soon as the stock
  dips below the strike. It collects the most premium of any structure here
  in exchange for almost no room on either side.

**P&L shape (short), per share:** max profit = total credit, only if the
stock finishes exactly at the strike. Breakevens: `strike ± total_credit`.
The probability of keeping the *full* credit is low by construction, so
report the estimated `pop` (probability of finishing above zero) rather than
implying the full credit is likely.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte`, use
that expiration. Don't pick or ask about a different one. Only fall back to
asking or picking one yourself when no page context is present.

**Building it:** `build_strategy` with `SHORT_STRADDLE`. The `short_put` leg
anchors the shared strike (default `atm`, the strike nearest spot). The call
is placed at the same strike automatically.

**When each fits:** long ahead of a known volatility catalyst with no
directional view; covered short as an income trade on a position already
held, expecting the stock to sit near the current price through expiration.
