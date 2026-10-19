# Credit Spreads (Put Credit Spread / Call Credit Spread)

Two-legged, same-expiration, defined-risk strategy: sell one option and buy
a further-OTM option of the same type as a protective wing, collecting a net
credit. It works like a short put or short call with its risk capped by the
wing, which also makes it the building block of an iron condor (see
iron_condor.md, which is one put credit spread plus one call credit spread).

- **Put credit spread (bullish to neutral):** sell a put below spot (K2), buy
  a lower put (K1 < K2). It profits if the stock stays above K2.
- **Call credit spread (bearish to neutral):** sell a call above spot (K1),
  buy a higher call (K2 > K1). It profits if the stock stays below K1. This
  is the *covered* way to sell a call: unlike a naked short call, the risk
  is capped at the spread, so no stock position is needed to cover it.

**P&L shape, per share:** max profit = net credit, kept if the short strike
expires worthless. Max loss = `wing_width − net_credit`, reached at or beyond
the long strike. Breakeven: `short_strike − net_credit` for a put spread,
`short_strike + net_credit` for a call spread.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte` (the
expiration pill the user already has open on StrikeLab), use that
expiration. Don't call `get_expirations` and choose a different one, and
don't ask the user which expiration they want. Only fall back to asking or
picking one yourself when no page context is present.

**Strike selection:**
- **Short strike: 0.30 delta or lower**, the same ceiling the other
  premium-selling strategies here use. Pull `get_price_history` and prefer a
  short put at or below support (or a short call at or above resistance) if
  one is close to that delta. If the delta and the level don't line up, say
  so rather than picking one arbitrarily.
- **Wing width** sets the risk. A wider wing collects more credit but has a
  larger max loss. State the max loss in dollars (× contract multiplier),
  not only per share.
- **Credit relative to width:** report `returnOnRisk` (max profit / max
  loss) and the credit as a fraction of the wing width. A spread collecting
  only a small fraction of its width (e.g. under ~20%) is a poor
  risk/reward even at a low delta, so mention that rather than presenting
  it as attractive.

**Building it:** `build_strategy` with `PUT_CREDIT_SPREAD` or
`CALL_CREDIT_SPREAD`. The short leg is the anchor
(`{"mode": "delta", "value": 0.20}` and so on). The wing takes `width` in
dollars, or `steps` (number of listed strikes) when the chain's strike
spacing is uneven. Check the returned short-leg delta against the ceiling
above, and check `naturalPremium` is still a credit.

**When each fits:** a put credit spread for a mildly bullish or "won't fall
below X" view with defined risk (where a cash-secured put would tie up too
much capital), and a call credit spread for a mildly bearish or "won't rise
above Y" view. Avoid holding either through a known binary catalyst
(earnings) right at the short strike.
