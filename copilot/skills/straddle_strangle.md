# Straddle & Strangle

Two-legged, same-expiration strategies that bet on the *magnitude* of a
move rather than its direction — can be run long (buying volatility) or
short (selling volatility).

**Straddle:** same strike (typically ATM) for both the call and the put.
**Strangle:** different, further-OTM strikes for the call and put — cheaper
to buy / less premium to sell than a straddle, but needs a bigger move to
reach the same payoff for the long version, and has a wider profit range
for the short version.

**Long (buy both legs):** profits from a large move in either direction —
common ahead of a known binary catalyst (earnings, FDA decision) where the
direction is uncertain but a big move is expected. Max loss is the total
premium paid, if the stock sits still through expiration. Net vega-positive
and theta-negative — this is a bet that realized volatility (or IV
expansion) outpaces time decay, so it loses value on quiet days even if the
outlook is eventually right.

**Short (sell both legs):** profits if the stock stays range-bound, the
mirror-image bet — collects premium upfront, net theta-positive and
vega-negative. **Undefined/very large risk**: unlike the credit spreads or
iron condor above, there's no long leg capping the loss on either side — a
sharp move against a short straddle/strangle can produce losses far
exceeding the premium collected. Generally only appropriate with a strategy
for actively managing/closing the position if the stock starts to break out,
not a set-and-forget income trade.

**When each fits:** long version ahead of a known volatility catalyst with
an uncertain direction; short version as a range-bound income bet only with
real risk management in place, given the uncapped downside.
