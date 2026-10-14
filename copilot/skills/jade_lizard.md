# Jade Lizard

Three-legged, same-expiration credit strategy: **sell 1 put** below spot,
plus a **call credit spread** above spot (sell 1 call, buy 1 higher call).
Its defining property is that **the total credit is at least as large as the
call spread's width**, so there is **no risk to the upside**. If the stock
rallies through both calls, the call spread's max loss is paid for by the
credit already collected.

**Legs, in strike order: short put (K1) < spot < short call (K2) < long call
(K3).**

**HARD STRUCTURAL CONSTRAINT, checked before anything else:** all three legs
must be present, strictly ordered K1 < K2 < K3, and
`total_credit ≥ K3 − K2` using the actual bid/ask (`naturalPremium` from
`build_strategy`, not the mid). A candidate that fails this has upside risk
and is not a jade lizard. It's a short put plus a call spread with risk on
both sides, so don't present it as one. Pick different strikes (a narrower
call spread, or a closer short put for more credit), or say none qualifies
in range.

**P&L shape, per share:**
- Above K3: profit = `total_credit − (K3 − K2)`, which is zero or positive by
  the constraint above.
- Between K1 and K2: max profit = total credit.
- Below K1: loses $1 for each $1 the stock falls further, like a naked put.
  Breakeven = `K1 − total_credit`. The downside is **the short put's risk**:
  bounded only by the stock going to zero.

**Treat the put leg exactly like a short put.** Everything the naked put and
cash-secured put guidance says about the put applies here:
- **0.30 delta or lower** on the short put.
- Place the short put at or below a support level from `get_price_history`
  where possible.
- Check the rest of the account (buying power, existing exposure on the
  same underlying and expiration) before recommending it.

The call spread is there to add credit, not to change the downside.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte`, use
that expiration. Don't pick or ask about a different one. Only fall back to
asking or picking one yourself when no page context is present.

**Building it:** `build_strategy` with `JADE_LIZARD`. Anchors are
`short_put` (delta, default 0.30) and `short_call` (delta, default 0.20). The
`long_call` wing defaults to **1 listed strike** above the short call, since
the credit has to cover the call spread's width, which wide wings rarely
allow. The tool already rejects combinations whose mid credit doesn't cover
the width. Re-check against `naturalPremium` before presenting, since bid/ask
is stricter than mid. If the defaults don't qualify, try a lower-delta short
call with the same 1-strike wing, or a slightly higher-delta short put
(still ≤ 0.30).

**When it fits:** a neutral-to-bullish view where the trader is happy to own
the stock at the short put strike (as with a cash-secured put), and wants
extra premium from the upside without taking on upside risk. Elevated IV
helps, since it makes the "credit ≥ width" condition reachable at sensible
deltas.
