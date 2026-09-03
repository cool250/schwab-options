# Calendar Spread (Time Spread)

Selling a near-term option and buying a further-dated option at the same
strike (same type — both calls or both puts) — a bet on time decay and
implied volatility term structure rather than direction.

**Mechanics:** the short (near-term) leg decays faster than the long
(far-term) leg as expiration approaches, since theta accelerates for
options closer to expiry. Max profit is realized if the stock is at or near
the strike when the near-term leg expires, letting it expire worthless (or
be closed cheaply) while the long leg retains most of its value. Net debit
strategy — pay to enter, unlike the credit strategies above.

**When it fits:** a neutral, low-movement outlook through the near-term
expiration, plus a view that near-term implied volatility is elevated
relative to longer-dated IV (selling the "expensive" front-month leg,
buying the relatively "cheap" back-month leg) — this makes it a
volatility-term-structure trade as much as a directional one.

**Risk profile:** max loss is capped at the net debit paid, realized if the
stock moves far from the strike in either direction before the near-term
expiration. Net vega-positive overall (the longer-dated long leg has more
vega than the short leg), so the position benefits from IV rising, the
opposite exposure from most of the credit strategies above. Best entered
when front-month IV is high relative to back-month IV (positive term-
structure skew), not the reverse.
