# Covered Call — Equity Options

**Legs: own 100 shares + sell 1 call (usually OTM) per 100 shares.** The
shares cover the call: if it's assigned, the shares are delivered at the
strike, so there's no upside loss — the position just stops gaining above
the strike. It's the call side of the wheel (sell puts → get assigned →
sell calls on the shares).

**Numbers, per share (× 100 per contract), shares at cost S, call strike K,
premium C:**
- Max profit = C + (K − S), reached at or above K (shares called away).
- Max loss = C − S, if the stock goes to zero — the shares' risk, cushioned
  by the premium.
- Breakeven = S − C.
- Unchanged price: keep C. That's the Screener's covered-call ROI (C ÷ spot,
  annualized); `build_strategy` reports return on risk instead
  (max profit ÷ max loss), which also counts the move up to the strike.

**When it fits:** neutral to mildly bullish on shares the user already owns
(or is willing to hold), wanting income and accepting that gains above the
strike are given up. A stock they'd hate to sell is a reason for a further
OTM strike, or not to sell the call at all.

**Check the account first.** Pull `get_stock_positions`: the user needs at
least 100 shares per call. Without them it's not a covered call — don't
recommend a naked short call in its place (unlimited risk). Also check
`get_option_positions` for calls already sold against the same shares, so
the shares aren't covering two calls at once.

**Strike selection:** around **0.30 delta or lower** is the usual starting
point — higher deltas pay more but get called away more often. If the
user's cost basis is above spot, prefer a strike at or above the cost basis
so an assignment doesn't lock in a loss on the shares (say so if no strike
there pays meaningfully).

**Building it:** `build_strategy` with strategy `COVERED_CALL` places the
`short_call` leg (default delta 0.30) and prices the position with 100
shares per contract bought at spot; its result carries `shares` alongside
the legs. `propose_legs` only carries option legs, so "Apply" sends the
call alone — tell the user the shares aren't included there, or have them
use the Analyze page's Strategy Builder (Covered Call), which applies the
shares too.
