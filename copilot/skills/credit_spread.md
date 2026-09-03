# Credit Spread (Vertical)

Selling one option and buying a further-OTM option of the same type and
expiration, to collect a net premium with a defined, capped max loss —
unlike a naked CSP or covered call, both legs are options, so there's no
stock ownership involved.

**Two variants:**
- **Put credit spread (bull put spread):** sell a higher-strike put, buy a
  lower-strike put. Bullish/neutral — profits if the stock stays above the
  short strike.
- **Call credit spread (bear call spread):** sell a lower-strike call, buy a
  higher-strike call. Bearish/neutral — profits if the stock stays below the
  short strike.

**Mechanics:** net premium collected = short leg premium − long leg premium.
Max profit = that net credit, realized if the stock finishes on the
favorable side of the short strike at expiration. Max loss = (strike width
− net credit) × 100, capped by the long leg no matter how far the stock
moves against the position.

**When it fits:** a directional-but-not-certain view, or wanting defined
risk without tying up strike × 100 in collateral the way a naked CSP does —
margin/collateral requirement is just the max loss, not the full notional.

**Risk profile:** the long leg caps both the max loss and (slightly) the
max profit compared to the naked short version, in exchange for using far
less capital. Net theta-positive and net vega-negative, but smaller in
magnitude than a naked single-leg position since the long leg's greeks
partially offset the short leg's.
