# Covered Call

Selling a call option against shares you already own — the exit leg of the
wheel, but usable standalone on any long stock position.

**Mechanics:** own 100 shares per contract, sell 1 call, strike typically
above the current price (OTM). Collect premium upfront. At expiration: if
the stock is below the strike, the call expires worthless, keep the shares
and the premium; if above, shares are called away at the strike (effective
sale price = strike + premium collected).

**When it fits:** shares already held that the trader is willing to sell at
the strike, and/or a neutral-to-mildly-bullish near-term outlook — selling
calls into a stock expected to run hard works against the position, since
upside above the strike is given up in exchange for the premium.

**Risk profile:** the call itself doesn't add downside risk beyond already
owning the shares (the premium collected is a small cushion against a
decline), but it caps upside at the strike + premium. Short option:
theta-positive, vega-negative, delta negative (works against the stock's
own long delta, partially offsetting it).

**Strike/expiration tradeoffs:** same shape as the CSP side — closer/shorter
= more premium and theta but higher odds of the shares being called away
and less room for the stock to run before capping out. Choosing a strike
above cost basis avoids realizing a loss on assignment even if it does get
called away.
