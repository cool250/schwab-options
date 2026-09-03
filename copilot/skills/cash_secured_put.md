# Cash-Secured Put (CSP)

Selling a put option while holding enough cash to buy the underlying at the
strike if assigned — the entry leg of the wheel, but usable standalone.

**Mechanics:** sell 1 put contract, strike below the current price (OTM) in
most cases, and set aside strike × 100 in cash as collateral. Collect the
premium upfront. At expiration: if the stock is above the strike, the put
expires worthless and the premium is pure profit; if below, you're assigned
100 shares at the strike (effective cost basis = strike − premium
collected).

**When it fits:** neutral-to-bullish outlook on a stock you'd genuinely be
willing to own at the strike price — this should be treated as a real buy
order with a premium discount, not just a way to collect income, since
assignment is a real possible outcome, not a tail risk.

**Risk profile:** max loss is (strike − premium) × 100 if the stock goes to
zero — identical downside to buying the shares outright at that effective
price. Max gain is the premium collected, capped, realized if the put
expires worthless. Short option: theta-positive, vega-negative, delta
positive but small in magnitude for OTM strikes (moves the same direction
as the stock, just muted).

**Strike/expiration tradeoffs:** shorter-dated and closer-to-the-money =
more premium relative to time, more theta decay per day, but higher
assignment odds and more gamma risk near expiration. 30-45 DTE at a
~0.20-0.30 delta is a common starting point balancing premium income against
assignment frequency.
