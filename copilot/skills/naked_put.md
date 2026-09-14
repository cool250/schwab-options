# Naked Put — Futures Options Only (e.g. /ES, /NQ)

**Scope: this strategy applies to futures options, not equity options.**
Unlike an equity put, a futures put has no real "cash-secured" equivalent
in the first place — there's no share-purchase mechanic to set aside full
collateral against, so a short put on a futures product is inherently
margin-based (SPAN/portfolio margin) from the start. "Naked" here just
means: sell 1 put on a futures contract (e.g. /ES, /NQ), typically OTM,
collect the premium, backed by margin rather than a dedicated cash reserve.

**Mechanics:** sell 1 put on the futures product, collect premium upfront.
At expiration: above the strike, the put expires worthless and the premium
is kept; below the strike, assignment means taking a **long futures
position** at the strike (not shares) — effective entry price = strike −
premium, per point. Dollar amounts scale by the product's own contract
multiplier, not a flat ×100 like equities — e.g. /ES is $50/point, /NQ is
$20/point (check the actual product's multiplier rather than assuming).

**When it fits:** a neutral-to-bullish view on the futures product with a
specific level in mind, sized against real margin/buying-power discipline
— usually paired with a plan to manage or close the position rather than
intending to hold into assignment, since taking on a long futures contract
carries its own ongoing margin requirement.

**Check the rest of the account before recommending one.** A new futures
put's margin draws on the same shared buying power as everything else
open, so it stacks with existing risk rather than sitting in its own silo:
- Pull `get_account_balances` for available cash/buying power headroom
  before sizing a new position.
- Pull `get_futures_positions` and `get_futures_option_positions` to see
  what's already open on this and other futures products — both the raw
  exposure and each position's own delta/direction. (`get_option_positions`
  /`get_stock_positions`/`get_total_exposure` cover equities only and don't
  reflect futures exposure — don't rely on them here.)
- Weigh the account's overall directional tilt, not just the new position
  in isolation: a short put adds positive delta (bullish exposure), and if
  existing futures/equity positions already skew long/bullish — especially
  on a correlated product (e.g. /ES and /NQ tend to move together) — another
  one makes the account's real aggregate bet larger than any single
  position suggests. Say so explicitly when that's the case rather than
  only evaluating the new put on its own.

**Expiration: use the one already selected on StrikeLab, don't pick your
own.** If the current-page context includes `selectedExpirationDte` (the
expiration pill the user already has open on StrikeLab), search that
expiration — don't call `get_expirations` and choose a different one, and
don't ask the user which expiration they want, since it's already right in
front of them. Only fall back to asking or picking one yourself when no
page context is present (e.g. the request comes with no StrikeLab context
at all).

**Strike selection — delta:** favor **0.30 delta or lower** as a starting
point — delta is a rough proxy for assignment odds, so a lower delta trades
some premium for a meaningfully higher chance of the put simply expiring
worthless.

**Premium/risk tradeoff:** frame the return relative to the margin actually
tied up, not a hypothetical full-notional basis. Compare candidates by
premium collected per day (annualized) rather than raw premium alone, since
a bigger premium on a longer-dated contract isn't automatically the better
trade once time-at-risk is accounted for — and don't reach for a
closer-to-the-money strike purely to chase more premium without weighing
the assignment-odds cost from the delta guidance above. Remember to convert
premium to real dollars via the product's contract multiplier, not ×100.

**Use the last 30 days of price history to find support, not delta alone.**
Pull `get_price_history` for the futures symbol (e.g. `/ES`) and look at
the support levels it returns (recent swing lows) before placing the
strike — delta is a statistical estimate, support is where the product has
actually found buyers.
- **Strike at/near a support level, at ≤0.30 delta:** the strongest
  combination — a level the product has held before *and* a lower
  statistical assignment probability.
- **Strike below the nearest support:** more conservative — assignment only
  happens if that support genuinely breaks, not just approaches.
If the two don't line up closely, say so rather than picking one
arbitrarily, and note that a 30-day lookback isn't a guarantee — a wider or
older window could show a different picture.

**Other things worth checking for strike/expiration placement:**
- **Liquidity:** prefer strikes with a tight bid/ask (from `get_option_chain`
  with the `/ES`-style symbol) — a wide spread eats into both the entry
  premium and the cost of closing or rolling the position later.
- **Don't chase locally elevated IV as free premium:** a chain's `iv` being
  high can mean rich premium, or it can mean the market is already pricing
  in a specific risk (a scheduled macro event, elevated volatility regime)
  — note when IV looks elevated rather than treating it as pure upside.
- **Avoid stacking several naked puts on the same expiration date** across
  products — doing so concentrates gap/timing risk onto a single day;
  staggering expirations spreads it out.
- **Define a management plan up front**, since margin, not a cash wall,
  contains the downside here — a specific close/roll trigger (e.g. buy back
  at some fraction of max profit, or roll down/out if a chosen loss
  multiple of the credit is breached) rather than a default "let it ride to
  expiration."
