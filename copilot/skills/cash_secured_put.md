# Cash-Secured Put (CSP)

Selling a put option while holding enough cash to buy the underlying at the
strike if assigned — the entry leg of the wheel, but usable standalone.

**Mechanics:** sell 1 put contract, strike below the current price (OTM) in
most cases, and set aside strike × 100 in cash as collateral. Collect the
premium upfront. At expiration: if the stock is above the strike, the put
expires worthless and the premium is pure profit; if below, you're assigned
100 shares at the strike (effective cost basis = strike − premium
collected).

**When it fits:** neutral-to-bullish outlook on a stock you'd genuinely be
willing to own at the strike price — this should be treated as a real buy
order with a premium discount, not just a way to collect income, since
assignment is a real possible outcome, not a tail risk.

**Risk profile:** max loss is (strike − premium) × 100 if the stock goes to
zero — identical downside to buying the shares outright at that effective
price. Max gain is the premium collected, capped, realized if the put
expires worthless. Short option: theta-positive, vega-negative, delta
positive but small in magnitude for OTM strikes (moves the same direction
as the stock, just muted).

**Strike/expiration tradeoffs:** shorter-dated and closer-to-the-money =
more premium relative to time, more theta decay per day, but higher
assignment odds and more gamma risk near expiration. 30-45 DTE at a
~0.20-0.30 delta is a common starting point balancing premium income against
assignment frequency; favor the lower end of that range (**0.30 delta or
lower**) when the priority is a higher probability of the put simply
expiring worthless over squeezing out extra premium — delta is a rough
proxy for assignment odds, so a lower delta trades some income for a better
win rate.

**Use support levels, not just delta, to place the strike:** delta gives a
rough statistical assignment probability, but it says nothing about the
stock's own recent price behavior. Before recommending or picking a strike,
pull `get_price_history` for the underlying and look at the support levels
it returns (recent swing lows) — they mark where the stock has actually
found buyers before, which is a more specific signal than delta alone. Two
common ways to combine them:
- **Strike at/near a support level, at ≤0.30 delta:** the strongest
  combination — it's already at or below the delta threshold favored above
  for win-rate, *and* the stock has historically held there, and if it
  doesn't this time, assignment happens at a level that was already
  "tested," not an arbitrary point.
- **Strike below the nearest support:** more conservative still — treats
  the support level as a line that's expected to hold, and sets the strike
  (and its delta, naturally lower still) further out so assignment only
  happens if that support genuinely breaks, not just approaches.
If support and the ≤0.30-delta strike don't line up closely, say so rather
than picking one arbitrarily — note the tradeoff (e.g. "the nearest support
is a bit above/below the 0.30-delta strike, so here's a level at each") and
let the user weigh probability-of-winning against how much premium is on
the table. A support level from a short lookback window isn't a guarantee
either — note that in the recommendation (e.g. "support from the last 30
days") rather than stating it as a hard floor, since older or wider-window
support/resistance could differ from what `get_price_history`'s default
30-day window shows.
