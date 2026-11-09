# Options Wheel — Recommending the Next Trades From the Current Book

Use this when the user asks what to trade next, how to run the wheel, or how
to adjust their book: new puts and calls to sell, and positions to cut. It
works across equities (shares, equity options) and futures (/ES, /NQ and
their options). **Recommendations only — nothing here is ever placed.**

## 1. Start from the snapshot

Call `get_wheel_snapshot` and `get_trade_feedback_summary` first, then the
position tools for the details
(`get_stock_positions`, `get_option_positions`,
`get_futures_positions`, `get_futures_option_positions` — the futures ones
carry live prices and unrealized P&L). Lead the answer with a short table:
net liquidity, notional, leverage, mode, MTD / YTD realized P&L, loss
budget. Use the snapshot's numbers as given; don't recompute them.

The feedback summary is what the user turned down before, and why. Shape
this answer by it: if they've rejected /NQ ratios for too much assignment
loss, lead with the milder structure there; if credits were too small,
don't offer a token premium. The rules below still win over a preference.

## 2. The mode sets how much risk to add

`mode` comes from leverage (notional ÷ net liquidity) and the bands in the
snapshot; `new_trade_delta_pct` is the delta range for new short puts and
calls in that mode (hundredths: [20, 30] = 0.20–0.30; puts `null` in
defensive mode). Both are settings in config/app.properties, shared with
the Home page's New Income ideas — quote them, don't invent others:

- **aggressive** (below the lower band): add premium. New short puts and
  covered calls in the mode's delta ranges; covered call ratios allowed
  (see 4). Size so leverage after the trades stays
  **below the defensive band**.
- **neutral** (between the bands): add selectively. New short puts in the
  mode's (lower) put range, only if leverage after the trade stays below the
  defensive band; prefer selling calls against what's already held over
  new puts, since covered calls add income without adding notional.
- **defensive** (at or above the upper band): **no new short puts and no
  new long futures.** Work the book down:
  1. Sell covered calls on long futures and shares that have free cover —
     in the mode's (higher) call range: more premium and more cushion, accepting
     the position may be called away (that also cuts notional). For a long
     future that's underwater (spot below entry), where a call at or above
     entry pays too little, use a **wind-down call ratio** (section 4a).
  2. Close short options that have already kept most of their premium
     (`take_profit_pct` in the snapshot) — that frees margin at a profit.
  3. Roll tested short puts (strike near or above spot) out in time and
     down in strike **for a net credit**.
  4. Only then close or trim at a loss — within the loss budget (see 5).

Leverage after a new trade: (`notional_total` + added notional) ÷
`net_liquidity`. A short put adds strike × contracts × multiplier (100 for
equity, the point value for /ES 50, /NQ 20); a covered call adds nothing.
Show it for each recommendation.

## 3. Never a naked call — check `call_coverage` before every call trade

For each underlying, `free_cover` is how many more short calls can be sold
with every one covered (by lots of 100 shares, long futures, or long calls
expiring on or after the latest short call). **New short calls minus new
long calls in the trade must not exceed `free_cover`.** If the snapshot
already shows `naked` > 0 anywhere, say so first: the fix (buy back the
extra calls, or buy a long call / future to cover them) comes before any
new trade.

- One /ES or /NQ option is covered by one future of the same root (/ES
  options by /ES futures — never across roots).
- Coverage works both ways: **closing or trimming a long future, shares or
  a long call removes cover.** Before recommending one, check the short
  calls it covers — if `free_cover` would drop below zero, pair it with
  buying back that many short calls.
- A short put that's in the money can be assigned into a new long future
  or shares — more notional, not less. Flag it when the mode is defensive.
- Equity calls: one per 100 shares.

## 4. Calls against futures: covered calls and covered call ratios

On long /ES or /NQ futures with free cover:

- **Covered call** — sell 1 call per long future. Read the `covered_call`
  doc for strike rules (it's written for shares; for futures the "100
  shares" is one future). Above the strike the future and call offset, so
  upside is capped, not lost.
- **Covered call ratio (1×2)** — buy 1 call, sell 2 higher calls: the
  long call covers one short, a long future must cover the other. Read the
  `call_ratio_spread` doc for strikes and the credit rule. Its "unlimited
  upside risk" warning is about the uncovered extra call — here that call
  is covered by the future, so say which future covers it, and that the
  structure caps the future's upside above the short strikes instead.
  Allowed only when `free_cover` ≥ 1 after the trade's own long call.

Use `build_strategy` (`COVERED_CALL`, `RATIO_CALL`) to place strikes, then
check coverage as above. `COVERED_CALL`'s max profit / loss assume the
shares or future are bought at spot today; for one already held, work the
outcome from the user's own entry — per lot (section 4b), not the average.

## 4a. Winding down long futures with call ratios (1×2 to 1×3)

The way out of long futures without waiting for a full recovery or closing
at the bottom: **buy 1 call nearer the money and sell 2 (or 3) calls out of
the money, for a net credit** — every short call beyond the long one
covered by a long future. If the market rallies through the short strike,
a few futures are called away at that strike and the long call adds the gap
between the strikes; if it doesn't, the credit is kept and the futures are
still held for the next cycle.

**Be aggressive here: having a few lots called away at a small loss is an
acceptable outcome, not a failure.** The rally that assigns them also lifts
every lot that stays open, so judge the trade on the whole root's result
in that rally (below), not on the assigned lots alone. Prefer the
structure that winds down the most futures for the best credit — the 1×3
when two lots are free — over a token-premium 1×2 struck far above the
entries.

**Expiration:** look **3–6 weeks out** first (`build_strategy` with a
`max_dte` range). Calls that far out of the money pay almost nothing within
a week, so a short-dated ratio rarely clears a credit; if no expiration in
that window does, say so rather than settling for a token premium.

**Structure (same expiration, net credit at natural prices):**
- Long call: at the money (`long_call` mode `atm`) — a long call just below
  the short strike leaves almost no gap for the outcome below.
- Ratio: **1×2 (buy 1, sell 2) or, more aggressively, 1×3 (buy 1, sell 3)
  — never wider.** Every short beyond the long call needs a long future of
  the same root: 1×2 needs 1 `free_cover`, 1×3 needs 2. With 2 free, lead
  with the 1×3 and show the 1×2 as the milder alternative.
- Short calls: anywhere from just out of the money up to the lots' entries,
  **never below `ratio_call_floors.by_root[root].lowest_short_strike`** in
  the snapshot (the cheapest open lot's trade price less
  `max_below_entry_pct`, a setting, 5% by default). Try a few strikes
  between the floor and the oldest lots' entry and pick the one with the
  best root result at assignment (below) that fits the loss budget —
  usually a strike near the next resistance, not the highest one that
  clears a credit. Below a lot's entry, assignment realizes a loss on that
  lot — work it out on the lots FIFO would actually close (4b), not on the
  cheapest one, and show it.
- The short calls must be out of the money (strike above spot). There's no
  delta ceiling here: being called away at or near the entry is the point
  of a wind-down, and the floor and the loss budget are what limit it — but
  show the short calls' delta as the rough chance that happens. Prefer a
  strike at or above a resistance level (see the `call_ratio_spread` doc).
- **Check the strikes `build_strategy` returns**: when nothing at the
  requested strike clears a credit it moves the short strike — reject any
  candidate whose short strike is below the floor, or whose long strike
  isn't below the short strike.

**Outcome at expiration, per structure — show this in points and dollars
(× point value: /ES 50, /NQ 20):**
- Below the long strike: + net credit; the futures are still held.
- At or above the short strike, two figures — show both:
  1. **Assignment result** (realized): (short strike − long strike) + net
     credit + Σ (short strike − entry) over the lots the covered shorts
     would close (4b).
  2. **Rally offset** (unrealized): (short strike − spot) × each long lot
     of that root that stays open — not called away by this trade or by
     calls already sold that the same move would assign.
  **Root result = assignment result + rally offset.** That's what counts
  against the loss budget: a candidate is in when the root result is a gain,
  or a loss within the budget left. Say plainly that the offset is a paper
  gain on lots still held — it's real only as long as the rally holds.
- In between: the long call gains as the futures recover; nothing is
  called away.

**Building it:** `build_strategy` with `RATIO_CALL` and params
`short_call` mode `strike` at the chosen strike (and `long_call` by delta
or strike). A 1×3 is that 1×2 plus one `COVERED_CALL` at the same short
strike and expiration (its short call only — the builder's shares aren't
part of the trade) — check the combined credit at natural prices and the
coverage for all three shorts.

**Say plainly:** these calls cushion the futures by the credit only — a
fall keeps losing on the futures. Laddering across expirations (one or two
futures' worth per cycle) winds a large book down gradually rather than
betting it on one expiration.

## 4b. Plan with each lot's own entry, not the average

`get_futures_positions` gives each root's blended `trade_price` and its
open `lots`, oldest first — each with its own date, quantity, entry
(`trade_price`) and `unrealized_pl`. **Plan with the lots.** When futures
are sold or called away, the **oldest lots close first** (FIFO — how this
app matches futures; check the broker's statement if a lot's realized
result matters for taxes), so:

- The result of an assignment at strike K that closes k futures is
  Σ (K − entry) × point value over the **k oldest lots still open** — not
  k × (K − average), and not the lot a call was sized against for coverage
  (below): coverage is counting, but an assignment realizes P&L on the
  oldest lots. If earlier calls may expire first, those oldest lots are
  still open then — use them. Show it per lot. For a covered call that
  realized figure is what counts against the loss budget; for a wind-down
  ratio it's the root result in 4a (net of the rally offset).
- The strike that loses nothing on assignment is at or above the highest
  entry among the lots it would close. Covering more futures reaches into
  newer lots, with their own entries — work out each step.
- Calls already sold use up coverage in the same order: count the oldest
  lots as covered by the existing short calls first (earliest expiration
  first), and size new calls against the lots left.
- Trimming futures outright closes the oldest lots too — quote the loss on
  those lots, not on the average.
- Show a lot table (date, qty, entry, unrealized P&L) before the
  recommendations whenever futures are involved.

## 5. Selling positions with minimal loss — the loss budget

`loss_budget.dollars` is the most a recommended close or roll may realize
as a loss (a share of the year's realized profit; zero if the year is a
loss). Rules:

- Prefer, in order: let it expire or close for a profit → roll for a net
  credit → cover with calls (futures, shares; a wind-down call ratio, 4a)
  → close at a loss.
- A close at a loss: give the realized loss, and keep the total of every
  loss recommended in one answer within the budget. If cutting risk needs
  more than the budget, say so and give the trade-off rather than
  exceeding it silently.
- The net-credit rule applies to **entries and rolls**; a plain close is a
  debit by nature and is judged by this budget instead.
- A covered call struck **below** the entry of the lot it would close
  (4b) locks in a loss if it's assigned: (lot entry − strike − premium) ×
  point value per contract. Prefer strikes at or above that entry; if a
  lower one is
  the right defensive trade, count that locked-in loss against the budget
  like a close.

## 6. What to return

A table of recommendations, best first: action, contract
(`TICKER MM/DD/YYYY STRIKE P/C`), quantity, credit (natural / mid), delta,
POP, added notional, leverage after, and what covers each short call. Then
one or two sentences on why this mode leads to these trades. In the app,
call `propose_legs` for the top new trade only (the Apply button stages one
position).
