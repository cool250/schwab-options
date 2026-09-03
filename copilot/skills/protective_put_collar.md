# Protective Put & Collar

Hedging strategies for an existing long stock position, rather than
income-generation strategies.

**Protective put:** buy a put against shares already held, like insurance —
if the stock drops, the put gains value to offset the loss below the
strike. Costs a premium outright (no credit collected), which is the max
loss on the hedge itself if the stock doesn't drop. Caps downside at
(strike − premium) below the stock's current price while leaving upside
fully open, unlike a covered call.

**Collar:** combine a protective put (bought) with a covered call (sold) on
the same shares — the call premium offsets some or all of the put's cost,
often making the hedge free or near-free ("costless collar"). In exchange,
upside is capped at the call strike, same tradeoff as a plain covered call,
stacked on top of the downside protection from the put.

**When each fits:** protective put when the trader wants to stay fully
exposed to upside but is worried about a near-term drop (earnings, macro
event) and is willing to pay for that insurance. Collar when the trader
wants to reduce or eliminate hedging cost and is fine giving up some upside
to do it — common for a large concentrated position the trader doesn't want
to sell outright but wants to de-risk.

**Risk profile:** both reduce downside risk versus plain stock ownership.
The protective put alone doesn't cap upside (the long put's negative delta
is small relative to the stock's, so net position stays close to full
delta-1 exposure above the strike); the collar caps both sides, turning the
position into something closer to a defined range of outcomes.
