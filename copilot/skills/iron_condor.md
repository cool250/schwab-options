# Iron Condor

A put credit spread and a call credit spread on the same underlying and
expiration, both sold together — a defined-risk bet that the stock stays
within a range through expiration.

**Mechanics:** sell an OTM put + buy a further OTM put (put credit spread),
and sell an OTM call + buy a further OTM call (call credit spread), all four
legs same expiration. Net premium collected = sum of both spreads' credits.
Max profit = that combined net credit, if the stock finishes between the
two short strikes. Max loss = (wider spread's width − net credit) × 100,
capped, if the stock breaks out past either long strike.

**When it fits:** a neutral outlook — expecting the stock to stay range-bound
through expiration, common heading into a period with no major expected
catalyst. Benefits from elevated IV at entry that's expected to fall
(vega-negative on both sides).

**Risk profile:** defined max loss on both sides, unlike a short strangle.
Theta-positive as long as the stock stays inside the short strikes; gamma
risk increases sharply near expiration if the stock is testing either
short strike. The profit zone is the range between the two short strikes,
minus/plus the credit collected at each breakeven.

**Strike selection:** the width between short and long strikes on each side
sets the max loss (and how much margin/collateral is required); the
distance from current price to each short strike sets both the probability
of staying in the profit zone and how much premium is collected — a common
approach is symmetric deltas (e.g. ~0.15-0.20 delta) on both the put and
call short strikes.
