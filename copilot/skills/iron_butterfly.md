# Iron Butterfly

Four-legged, same-expiration, defined-risk credit strategy: a **short
straddle** (sell a put and a call at the same at-the-money strike) with a
**protective wing on each side** (buy a lower put and a higher call). It
works like an iron condor (see iron_condor.md) whose two short strikes have
been pushed together to the same strike. It collects much more credit than a
condor of the same width, but has a much narrower zone of full profit.

**Legs, in strike order: long put (K1) < short put = short call (K2, ≈ spot)
< long call (K3).** Wings are usually equal width (`K2 − K1 = K3 − K2`).

**HARD STRUCTURAL CONSTRAINT:** all four legs must be present, both short
legs at the same strike, and both wings present and outside it
(K1 < K2 < K3). Without the wings it's a naked short straddle, which is only
ever recommended covered (see straddle.md). Never substitute one silently.

**P&L shape, per share:** max profit = net credit, only if the stock
finishes exactly at K2. Max loss = `wing_width − net_credit`, at or beyond
either wing. Breakevens: `K2 ± net_credit`. The credit is large relative to
the width, so `returnOnRisk` is often above 1. The probability of keeping
the *full* credit is low, though. Report the estimated `pop` (finishing
above zero), and frame the trade as "profit if the stock stays within
±credit of K2". Don't present max profit as the expected outcome.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte`, use
that expiration. Don't pick or ask about a different one. Only fall back to
asking or picking one yourself when no page context is present.

**Strike selection:**
- **Body (K2):** the strike nearest spot. Moving it off-center turns this
  into a directional bet (a "broken-wing" or skewed fly), so do that only
  when the user has asked for a lean.
- **Wing width:** wider wings collect more credit and widen the breakevens,
  but raise the max loss. State the max loss in dollars
  (× contract multiplier). Pull `get_price_history`: wings at or beyond
  recent support/resistance cap the loss where a move would already have
  broken a level.

**Building it:** `build_strategy` with `IRON_BUTTERFLY`. `short_put` anchors
the body (default `atm`), and the short call is placed at the same strike
automatically. `long_put` and `long_call` are wings: `width` in dollars
(default 10), or `steps`. Confirm `naturalPremium` is a credit.

**When it fits:** a strong "the stock pins here" view (low expected movement,
often into expiration week), or as a defined-risk substitute for a short
straddle when there's no position to cover the call. It's a poor fit ahead
of a binary catalyst.
