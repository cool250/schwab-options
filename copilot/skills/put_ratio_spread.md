# Put Ratio Spread

Buy one put at a higher strike and sell more puts (typically two) at a
lower strike, same expiration — a bullish-to-neutral strategy financed
partly or entirely by the extra short put, in exchange for taking on
uncapped downside risk below the short strikes.

**Mechanics (1x2 put ratio spread, the common version):** buy 1 put at a
higher strike, sell 2 puts at a lower strike. The extra short put's premium
substantially offsets (or fully pays for, or even nets a credit) the long
put's cost. Between the two strikes, the position behaves like a plain
debit put spread — max profit is realized right at the short strike, equal
to the strike width minus whatever net debit was paid (or plus the net
credit received). Below the short strike, the uncovered extra short put
takes over: for every $1 further the stock falls, the position loses $1 per
100 shares on that uncovered contract, same as a naked short put.

**When it fits:** a bullish-to-neutral outlook with a specific downside
level in mind — the trader is comfortable being naked short below the
lower strike (similar mindset to a CSP: willing to effectively buy more
stock down there), but wants a shot at a larger, spread-shaped payoff if
the stock lands near that strike rather than just collecting flat put
premium.

**Risk profile:** max profit is capped, at the short strike. Max loss is
effectively **uncapped** below the short strikes (limited only by the stock
going to zero, same as any naked short put) — this is the key thing that
distinguishes it from a defined-risk credit spread or iron condor, and
needs to be sized and margined accordingly. Above the long strike, if
entered as a net debit, the whole premium paid is at risk if the stock
just runs up and neither put ever goes ITM.

**Strike/ratio selection:** the ratio (2:1 is standard; wider ratios like
3:1 increase the credit/leverage and the downside risk proportionally),
and how far below the long strike the short strikes sit, both trade off how
much of the long put's cost gets offset against how much naked short
exposure is being taken on below that level.

**Use support levels — and delta — to place the short strike; this matters
more here than on a plain CSP.** The short strike is both where max profit
is realized *and* where the uncapped downside begins, so its placement does
double duty. Favor **0.30 delta or lower** on the short strike when the
priority is a higher probability of it simply expiring worthless rather
than maximizing the credit collected, same reasoning as a CSP — and pull
`get_price_history` for the underlying to check the support levels it
returns (recent swing lows) before picking it:
- **Short strike at/near a support level, at ≤0.30 delta:** the ideal
  combination — the max-profit outcome coincides with both a level the
  stock has actually held before and a lower statistical assignment
  probability, and the uncapped-risk zone only opens up if that support
  genuinely breaks, not on an ordinary pullback.
- **Avoid placing the short strike well above a nearby support** in an
  attempt to collect more credit — that leaves the max-profit point sitting
  in a range the stock could easily blow through on its way down to the
  level it's actually likely to test, turning what looked like the "sweet
  spot" into a strike that's already deep in the uncapped-loss zone.
Because the downside below the short strike is uncapped (not bounded at
zero like a CSP's), a support level that turns out to be weak or from too
short a lookback window is a bigger problem here — flag the lookback window
used (`get_price_history`'s default is 30 days) rather than treating it as
settled, and prefer a support level that's held across more than one recent
test over a single unconfirmed swing low.
