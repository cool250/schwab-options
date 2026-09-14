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

**HARD STRUCTURAL CONSTRAINT, checked before anything else: the short
strike(s) must be strictly below the long strike.** This is what makes it a
put ratio spread at all — not a preference, not something delta or credit
math can override. A candidate where the short strike is equal to or above
the long strike is not a valid put ratio spread, full stop, even if its
delta and net-credit numbers look fine in isolation — reject it and pick a
different short strike, don't present it. Concretely: after picking a
long strike (ATM or user-specified) and finding candidate short strikes,
throw out every candidate whose strike >= the long strike before applying
the delta/credit/distance reasoning below — the earlier general
description ("buy higher, sell lower") is a real invariant on the actual
strikes chosen from live chain data, not just a description of the typical
case.

**Strike selection — the rule, not just a preference: long leg at ATM,
short leg(s) at ≤0.30 delta, and the combination must price as a net
credit.** This is a firmer version of the general tradeoff (a
closer-to-ATM long strike protects better but costs more; a lower-delta
short strike has better odds of expiring worthless but collects less) —
resolved as a fixed starting point rather than something to balance case by
case. Compute it as `(short_qty × short_bid) − (long_qty × long_ask)` and
check the sign before presenting anything: a positive result is a real
credit; zero is break-even; **a negative result is a net debit, full stop —
never describe a negative number as "a small credit" or "net credit: -X",
and never present that configuration as the recommendation.** If it comes
out negative, that's the signal to work the delta/distance/ratio levers
below (or, per the hard constraint above, say plainly that no credit
version exists) — not a number to round past.
- **Long strike: ATM — unless the user explicitly specifies a different
  strike for the long leg, in which case use theirs instead, the same way
  an explicit ratio (below) overrides the 1:2 default.** The long put is
  the only thing capping the position's risk above the naked short strikes,
  and that protection is strongest when it has real delta from the very
  first dollar the stock drops, not just once it's fallen most of the way
  toward the strike. ATM also maximizes the strike width to the short leg,
  which is what sets the size of the max-profit zone. Don't substitute ATM
  when the user names their own long strike (e.g. "use the 190 put") —
  explain the ATM reasoning if it seems relevant, but an explicit
  instruction always wins over the default.
- **Short strike(s): 0.30 delta is a ceiling, not a default — start lower
  and only move up toward 0.30 if you need to.** Defaulting to exactly 0.30
  every time defeats the point of this rule: it's the *most* delta ever
  acceptable, not the target delta. Work the selection in this order:
  1. Start from a strike noticeably further OTM than 0.30 delta (e.g. 0.20,
     0.15, or lower) — further from the long strike, which widens the
     max-profit zone.
  2. Check whether that strike (at the chosen ratio) still prices as a net
     credit. If yes, that's your answer — don't creep it back up toward
     0.30 just because a higher-delta strike would also have worked; more
     distance with a smaller-but-still-real credit beats less distance with
     a bigger one, per the reasoning below.
  3. Only move to a higher delta (closer to the long strike, up to the
     0.30 ceiling) if a lower-delta strike can't clear the net-credit
     constraint at the chosen ratio. Widening the ratio (if the user
     allows it) is also a lever here — see below — before giving up
     distance by climbing toward 0.30.
  Strike distance is what sets the size of the max-profit zone, which is
  the actual reason to reach for a ratio spread instead of a flat CSP in
  the first place — treat every strike this pushes toward 0.30 as a cost,
  not a free upgrade in premium.

  **Before concluding no strike satisfies these constraints, make sure
  you actually looked far enough.** `get_option_chain`'s default
  strike_count (20) is not guaranteed to reach far enough below the long
  strike to find a qualifying one — it returns the strikes closest to spot
  in total, which can be lopsided, and a short-DTE contract's delta can
  stay well above 0.30 for many strikes past what a default fetch
  returns. If the strikes you got back don't include one that's both below
  the long strike and at/under the delta ceiling, call `get_option_chain`
  again with a larger strike_count before telling the user no valid
  configuration exists on this expiration — that conclusion needs to
  survive a genuinely wide search, not just the first, default-sized one.
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
which strike from the start-low procedure above to use:
- **A short strike is good enough to suggest as long as it sits below the
  long strike and collects a net credit — that credit doesn't need to
  exceed roughly $200.** Landing at/near a support level is a bonus on top
  of that, not an added requirement: once the structural constraint (short
  strike below the long strike) and a real net credit (per the sign check
  above) are both satisfied, don't hold out for a bigger credit or a
  closer support match at the cost of giving up the distance the start-low
  procedure above already found. When it *does* land at/near a support
  level, that's the strongest version — the max-profit outcome then
  coincides with a level the stock has actually held before, and the
  uncapped-risk zone only opens up if that support genuinely breaks, not
  on an ordinary pullback — but it's not the bar for a valid suggestion.
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
