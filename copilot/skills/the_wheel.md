# The Wheel

A cyclical, income-focused strategy this app is built around: repeatedly sell
cash-secured puts on a stock you'd be happy to own, and if assigned, sell
covered calls against the shares until they're called away — then start over.

**Mechanics:**
1. Sell a cash-secured put (CSP) on a stock at a strike you'd accept as a
   purchase price, collecting premium.
2. If the put expires worthless, keep the premium and repeat step 1.
3. If assigned, you now own 100 shares per contract at the strike price
   (minus premium collected). Sell a covered call against those shares.
4. If the call expires worthless, keep the premium and repeat step 3.
5. If the call is assigned (shares called away), you're back to cash —
   return to step 1.

**When it fits:** a stock/ETF the trader is neutral-to-bullish on and
wouldn't mind holding through a drawdown, since assignment isn't a failure
mode — it's an expected branch of the strategy. Works best on liquid
underlyings with decent options premium (higher IV = more income, but also
more downside risk if assigned into a falling stock).

**Risk profile:** the put leg's max loss is the strike minus premium
collected, times 100, if the stock goes to zero — same downside as owning
100 shares outright, just entered at a discount from the premium. The call
leg caps upside once shares are held (assignment forgoes further gains
above the call strike). Both legs are short options: theta-positive
(benefits from time decay), vega-negative (benefits from IV dropping after
entry).

**Strike selection is the main lever:** further OTM = lower premium, lower
assignment probability; closer to ATM = higher premium, higher assignment
probability. Delta is commonly used as a rough assignment-probability proxy
(e.g. a -0.20 delta put is roughly a 20% chance of finishing ITM at
expiration).
