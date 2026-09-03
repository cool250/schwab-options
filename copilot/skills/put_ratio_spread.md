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
