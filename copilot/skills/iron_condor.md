# Iron Condor

Four-legged, same-expiration, defined-risk strategy that bets the underlying
stays *range-bound* through expiration: sell a put spread below spot and a
call spread above spot, collecting a net credit for both. Unlike a naked
strangle or a put ratio spread, every leg here is covered by another leg, so
both max profit and max loss are capped by construction.

**Legs, in strike order (low to high): long put (K1) < short put (K2) <
spot < short call (K3) < long call (K4).** The short put and short call are
the two premium-collecting legs, closer to the money; the long put and long
call are the protective wings, further out, each capping the risk on its
side. Read as two independent credit spreads sharing one expiration: a short
put spread (K1/K2) below spot and a short call spread (K3/K4) above spot.

**P&L shape:** max profit is the total net credit, realized if the stock
finishes anywhere between K2 and K3 (both short legs expire worthless). Max
loss is capped at `wing_width − net_credit` per contract (see the ratio
constraint below), realized if the stock finishes at or beyond either long
strike. Between a short strike and its long strike, P&L moves linearly
between those two extremes. Breakevens: `K2 − net_credit` on the downside,
`K3 + net_credit` on the upside.

**When it fits:** a genuinely neutral, range-bound outlook — expecting the
stock to sit still or drift mildly, not a directional bet with insurance
attached. Works best when IV is elevated relative to the trader's own
expectation for realized movement (selling rich premium on both sides), and
worst around a known binary catalyst (earnings, FDA decision) where a big
move in either direction is plausible.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte` (the
expiration pill the user already has open on StrikeLab), search that
expiration — don't call `get_expirations` and choose a different one, and
don't ask the user which expiration they want, since it's already right in
front of them. Only fall back to asking or picking one yourself when no
page context is present.

**HARD STRUCTURAL CONSTRAINT, checked before anything else: all four legs
must be present and strictly ordered K1 < K2 < spot < K3 < K4.** This is
what makes it an iron condor at all — not a preference, not something delta
or credit math can override. A candidate missing a wing (e.g. a naked short
strangle instead of two spreads), or with strikes out of this order, is not
a valid iron condor — reject it and pick different strikes, don't present
it. Both wings should be present even if the user only asks about "selling
some premium on both sides" — a naked strangle is a different strategy (see
strangle.md) with materially different (uncapped, on the call side)
risk, and shouldn't be substituted silently.

**THE RATIO CONSTRAINT — checked next, before presenting anything: max
profit ÷ max loss must be at least 2/3 (≈0.667).** This is a firm floor for
this app, not a preference to balance against other factors — a candidate
that doesn't clear it is not a valid recommendation, full stop, even if its
strikes otherwise look reasonable.
- Compute per contract, before applying the multiplier (it cancels out of
  the ratio, but keep both prices in the same units):
  ```
  net_credit   = (short_put_bid − long_put_ask) + (short_call_bid − long_call_ask)
  wing_width   = max(K2 − K1, K4 − K3)     # symmetric wings: put_width == call_width
  max_profit   = net_credit
  max_loss     = wing_width − net_credit
  ratio        = max_profit / max_loss
  ```
  `wing_width` uses `max()` rather than assuming symmetric wings because,
  with unequal wing widths, the position can only be pushed to max loss on
  one side at expiration — whichever side is wider sets the worst case,
  since the net credit was collected from both sides regardless of which
  one gets breached.
- **Equivalent shortcut, useful for scanning strikes without recomputing the
  ratio for every candidate: `ratio ≥ 2/3` is the same condition as
  `net_credit ≥ 0.4 × wing_width`.** (Algebra: `c/(w−c) ≥ 2/3` ⟺ `3c ≥
  2w − 2c` ⟺ `5c ≥ 2w` ⟺ `c ≥ 0.4w`.) The net credit needs to be at least
  40% of the wing width — a materially richer credit than a "classic" iron
  condor typically collects (often 20–33% of width), so expect this
  constraint to push strikes closer to the money than a textbook condor
  would use.
- **If the ratio isn't met, the levers are (in this order):**
  1. **Move the short strikes closer to the money first.** A short strike
     nearer spot collects more premium per point of width than a further-OTM
     one loses in width, which is usually the more efficient way to raise
     the credit-to-width ratio — but don't cross the 0.30-delta ceiling
     below without explicit user permission (see strike selection).
  2. **Narrow the wing width** (bring the long strikes closer to the short
     strikes) if the short strikes are already near the delta ceiling. A
     narrower wing directly shrinks `max_loss` for the same credit, raising
     the ratio, at the cost of a smaller max-profit zone in dollar terms
     (though not in ratio terms) and less protection if the short leg is
     breached.
  3. If neither lever gets there within the delta ceiling below, **say so
     plainly — this underlying/expiration doesn't support a 2/3-ratio iron
     condor** — don't loosen the ratio floor or present a sub-2/3 candidate
     as "close enough."

**Strike selection for the short legs — delta:** favor **0.30 delta or
lower** on each short leg, same ceiling this app uses for every other
credit strategy — a lower delta trades some premium for a better chance
that side expires worthless. Given the ratio constraint above will often
push toward the ceiling rather than away from it, treat 0.30 as a hard cap
you may need to use, not a target to avoid.

**Before concluding no configuration meets these constraints, make sure you
looked far enough.** `get_option_chain`'s default strike_count (20) is not
guaranteed to reach far enough from spot to find qualifying strikes on both
sides — it returns the strikes closest to spot in total, which can be
lopsided, and a short-DTE contract's delta can stay well above 0.30 for many
strikes past what a default fetch returns. If the returned chain doesn't
include enough strikes on both sides to test the ratio properly, call
`get_option_chain` again with a larger strike_count before telling the user
no valid configuration exists on this expiration.

**Wing width — default to symmetric (put width == call width) unless the
user asks for a skewed condor.** Symmetric wings are the standard
convention and keep the position's risk simple to reason about; only build
unequal wings when explicitly requested, the same way put_ratio_spread.md
only widens its ratio off the 1:2 default on explicit request.

**Use support/resistance alongside delta to place the short strikes** —
same idea as the covered strangle's placement. Pull `get_price_history` for
the underlying and favor the support level for the short put and the
resistance level for the short call, the same way a CSP uses support alone.
If the ≤0.30-delta strike and the nearest support/resistance don't line up
closely, say so rather than picking one arbitrarily — and remember that
satisfying the 2/3 ratio may require sitting closer to spot than either
level suggests, in which case say that explicitly too rather than silently
overriding the support/resistance read.

**Other things worth checking for strike/expiration placement:**
- **Liquidity on all four legs:** prefer strikes with a tight bid/ask on
  every leg, not just the shorts — the long wings are cheap, low-open-interest
  contracts on many underlyings, and a wide spread there erodes the net
  credit (and the ratio) just as much as a wide spread on the shorts does.
- **Don't chase locally elevated IV as free premium:** a chain's `iv` being
  high can mean rich premium, or it can mean the market is already pricing
  in a specific risk (a scheduled macro event, elevated volatility regime)
  — note when IV looks elevated rather than treating it as pure upside.
- **Avoid stacking several iron condors on the same expiration** across
  underlyings — doing so concentrates gap/timing risk onto a single day;
  staggering expirations spreads it out.
- **Define a management plan up front**, since max loss (though capped) can
  still be a multiple of the credit collected — a specific close/roll
  trigger (e.g. buy back at some fraction of max profit, or roll the
  untested side in if one short strike is tested) rather than a default
  "let it ride to expiration."
