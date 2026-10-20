# Call Ratio Spread

Buy one call at a lower strike and sell more calls (typically two) at a
higher strike, same expiration — a neutral-to-moderately-bullish strategy
where the extra short call pays for the long call (and, entered correctly,
nets a credit), in exchange for **uncapped upside risk** above the short
strikes. It's the mirror image of the put ratio spread.

**Mechanics (1x2):** buy 1 call, sell 2 higher calls. Between the strikes it
behaves like a call debit spread: max profit is at the short strike, equal
to the strike width plus the net credit. Below the long strike every call
expires worthless and the trader keeps the net credit. Above the short
strike the uncovered extra call takes over — every $1 further the stock
rises loses $1 per 100 shares, with no limit.

**When it fits:** a view that the stock drifts up modestly (toward the
short strike) but doesn't break out — e.g. a capped, range-bound name or
one with clear overhead resistance. Not for a stock that could gap up on
news or earnings.

**Risk profile:** max profit capped at the short strike. Max loss is
**unlimited** above the short strikes — worse than a put ratio spread,
whose downside at least stops at zero. Say this plainly whenever you
present one, and size/margin it like a naked short call.

**Expiration:** same rule as the put ratio spread — use the expiration
already selected on StrikeLab (`selectedExpirationDte` in the page context)
rather than picking or asking for another.

**HARD STRUCTURAL CONSTRAINT: the short strike(s) must be strictly above the
long strike.** A candidate with the short strike at or below the long strike
is not a call ratio spread — reject it before any delta/credit reasoning.

**Strike selection — long leg near ATM (≈0.30–0.50 delta) unless the user
names a strike; short legs at ≤0.30 delta, starting lower (0.15–0.20) and
moving up only if needed to clear a net credit; must price as a net
credit.** Check `(short_qty × short_bid) − (long_qty × long_ask)` before
presenting: negative is a net debit — never call it a credit. Default ratio
1:2; don't widen it on your own initiative (more uncovered upside risk) —
ask first.

**Use resistance levels to place the short strike.** Pull
`get_price_history` and prefer a short strike at or just above a resistance
level the stock has held more than once: max profit then sits where the
stock has stalled before, and the unlimited-loss zone only opens if that
resistance genuinely breaks. Flag the lookback window used.

The Analyze page's Strategy Builder offers this as **Ratio Call (1×2)**
(`build_strategy` with `RATIO_CALL`), which applies the credit and
strike-order rules automatically.
