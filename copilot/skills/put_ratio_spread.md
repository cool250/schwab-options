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

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte` (the
expiration pill the user already has open on StrikeLab), search that
expiration — don't call `get_expirations` and choose a different one, and
don't ask the user which expiration they want, since it's already right in
front of them. Only fall back to asking or picking one yourself when no
page context is present.

**Strike selection — the rule, not just a preference: long leg at ATM,
short leg(s) at ≤0.30 delta, and the combination must price as a net
credit.** This is a firmer version of the general tradeoff (a
closer-to-ATM long strike protects better but costs more; a lower-delta
short strike has better odds of expiring worthless but collects less) —
resolved as a fixed starting point rather than something to balance case by
case:
- **Long strike: ATM.** The long put is the only thing capping the
  position's risk above the naked short strikes, and that protection is
  strongest when it has real delta from the very first dollar the stock
  drops, not just once it's fallen most of the way toward the strike. ATM
  also maximizes the strike width to the short leg, which is what sets the
  size of the max-profit zone.
- **Short strike(s): ≤0.30 delta.** Same reasoning as a CSP — a lower delta
  trades some credit for a meaningfully higher chance of the short leg(s)
  simply expiring worthless, which matters here more than on a plain CSP
  since the downside past that strike is uncapped, not bounded at zero.
- **Ratio: default to 1:2 (1 long, 2 short) — only use a different ratio if
  the user specifically asks for one.** Don't widen to 3:1, 4:1, etc. on
  your own initiative to fix a net debit or to reach for more credit; that's
  a real change to the position's risk (more uncovered short exposure below
  the short strike) and needs to be the user's call, not a silent
  adjustment. If ATM-long + ≤0.30-delta-short doesn't clear a net credit at
  1:2, say so plainly — note that a wider ratio would bring in more premium
  and ask whether they want to see that version, rather than just widening
  it and presenting the result as *the* recommendation. Likewise, don't
  narrow the long strike off ATM to force a credit at 1:2 — per the net-
  credit hard constraint, if neither the ratio nor the long strike is free
  to move, state clearly that no credit version exists at 1:2 for this
  underlying/expiration.

**Use support levels alongside delta to place the short strike; this
matters more here than on a plain CSP.** The short strike is both where max
profit is realized *and* where the uncapped downside begins, so its
placement does double duty. Pull `get_price_history` for the underlying to
check the support levels it returns (recent swing lows) before finalizing
which ≤0.30-delta strike to use:
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
