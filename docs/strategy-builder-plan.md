# Strategy Builder — Implementation Plan

_Drafted 2026-10-14, revised the same day with product decisions. Status:
phases 1–4 implemented 2026-10-14; phase 5 not started._

## Goal

On the **Analyze page** (`StrikeLab`, `/analyze`), once a ticker is
selected, a **"Build Strategy"** button opens an **overlay**. In it the user:

1. Picks **Net Credit** or **Net Debit**, which filters the strategy list.
2. Picks a **strategy type** (Short Put, Strangle, Iron Condor, Jade Lizard,
   Ratio Put, Long Call, Debit Spread, …).
3. Sets the leg **parameters** (target delta, % OTM, expected move, wing
   width, credit or debit target, expiration).
4. Clicks **Build**. The backend finds the real contracts on the live chain
   that best fit, and the overlay shows the result and a few alternatives.
5. Clicks **Apply**. The overlay closes and the legs land in Analyze's legs
   editor, where the existing payoff, P&L table and graph show them and the
   legs stay editable.

The builder only chooses and solves; it does not draw payoffs. Analyze
already does all of the viewing and editing.

### Decisions (2026-10-14)

- **Credit or debit is a selectable option**, not credit-only.
- **No IV filtering** (no IV rank or percentile gating). IV is still used to
  place strikes by expected move. That uses the chain's own ATM IV, which is
  already fetched.
- **Mid pricing** only, matching how Analyze prices manually added legs.
- The builder is an **overlay on Analyze**, opened only once a ticker is
  selected. There is no separate page or Navbar entry.

## What already exists (reuse, don't rebuild)

| Piece | Where | How the builder uses it |
|---|---|---|
| Ratio Put / Jade Lizard combination logic, payoff math, breakevens, capital, ROI | `service/screener_strategies.py` (`_payoff`, `_position_row`, `ratio_put_rows`, `jade_lizard_rows`) | Move the shared math into a common module. The builder and the screener both import it. |
| Single-expiration normalized chain (bid/ask/delta/iv per strike, ATM IV) | `OptionChainProvider.get_option_chain(symbol, dte, strike_count)` | The solver's input. It works with either `CHAIN_PROVIDER`. |
| Analyze's symbol, expirations, selected expiration (`expIndex`), spot | `StrikeLab.jsx` state | Passed into the overlay as its starting point |
| Analyze's leg-apply logic (replace legs, set `pendingExp`, widen range via `fitRangeToLegsRef`) | the copilot `apply()` effect in `StrikeLab.jsx` | Turn it into a named function that both the copilot Apply and the builder Apply call |
| Overlay pattern | `.landing-overlay` in `Landing.jsx` / `landing.css` (backdrop, click-outside to close) | Turn it into a generic `.overlay` style, or reuse its structure |
| Strategy reference docs | `copilot/skills/*.md` | Help text and copilot grounding. Add the missing ones. |
| UI building blocks | `HelpTip`, `.tab-row`, `DataTable`, `optionSymbol.js`, `contractMultiplier.js` | Form help, the credit/debit and anchor switches, the alternatives table, contract labels, futures multipliers |

## Strategies (v1)

Each strategy is a **template**: a list of leg specs, the rules it must
satisfy, and a **direction** tag (credit or debit). The Credit/Debit switch
only shows the templates with that tag. For credit templates the solver
requires net credit > 0. For debit templates it requires net debit > 0.

**Net Credit**

| Strategy | Legs | Default params | Rules |
|---|---|---|---|
| Short Put | −1 P | 30Δ | — |
| Short Call | −1 C | 30Δ | — |
| Put Credit Spread | −1 P, +1 P lower | short 30Δ, width $5 | — |
| Call Credit Spread | −1 C, +1 C higher | short 30Δ, width $5 | — |
| Strangle | −1 P, −1 C | 16Δ / 16Δ | put strike < call strike |
| Straddle | −1 P, −1 C, same strike | ATM (strike nearest spot) | — |
| Iron Condor | +1 P, −1 P, −1 C, +1 C | shorts 16Δ, wings $5 | put side entirely below call side |
| Iron Butterfly | +1 P, −1 P, −1 C, +1 C (shorts same strike) | ATM, wings $10 | — |
| Jade Lizard | −1 P, −1 C, +1 C higher | put 30Δ, call 20Δ, wing $5 | **credit ≥ call-spread width** (no upside risk), as in the screener |
| Ratio Put (1×2) | +1 P, −2 P lower | long 30Δ, shorts 15Δ | as in `put_ratio_spread.md` |

**Net Debit**

| Strategy | Legs | Default params | Rules |
|---|---|---|---|
| Long Call | +1 C | 50Δ | — |
| Long Put | +1 P | 50Δ | — |
| Call Debit Spread | +1 C, −1 C higher | long 50Δ, width $5 | — |
| Put Debit Spread | +1 P, −1 P lower | long 50Δ, width $5 | — |
| Long Straddle | +1 P, +1 C, same strike | ATM | — |
| Long Strangle | +1 P, +1 C | 25Δ / 25Δ | put strike < call strike |

Templates keep the leg *structure* fixed, and the parameters only move
strikes. If a combination's net premium comes out on the other side (a
"credit" spread priced at a debit), it fails the rules and isn't returned.
A new strategy should only need a new template entry. The solver and the UI
should not need changes.

## Parameters

Each leg group (short put, short call, long put, and so on) is placed by
**one** of these anchor modes. The mode is chosen per group in the form.

- **Delta**: the strike whose |Δ| is closest to the target. On a tie, take the
  strike further OTM.
- **% OTM / $ offset** from spot.
- **Expected move (σ)**: strike ≈ `spot · exp(±k · IV · √(dte/365))`, using
  the chain's ATM IV. A 1σ strangle sits at the edges of the expected move.
- **Explicit strike** (a manual override).
- **Wings** (the protective legs): width in **$** or in **strike steps**, or
  their own **delta**.

Position-level parameters:

- **Expiration**: defaults to the expiration currently selected on Analyze.
  The same expiration pills inside the overlay can change it.
- **Contracts** (quantity multiplier).
- **Credit or debit target** (optional): a *minimum* credit for credit
  strategies, or a *maximum* debit for debit strategies. If the initial
  placement misses it, the solver searches nearby strikes (see Solver).
- **Pricing**: always **mid**, `(bid + ask) / 2`. A contract counts as usable
  only if it has both a bid and an ask.

## Solver (backend)

`service/strategy_builder.py`, through `MarketService.build_strategy(...)`.

1. Fetch one expiration with
   `option_chain_provider.get_option_chain(symbol, dte, strike_count=N)`.
   Use a wide enough N (~40–60 per side) so that 5–10Δ legs and their wings
   are inside the window.
2. **Initial placement**: resolve each anchored leg by its mode, then each
   wing relative to its anchor leg.
3. **Check the template's rules**, including the credit or debit direction.
4. **Target search**, only when a credit/debit target is set or the rules
   fail: move each anchored leg ±1…K strike steps (K≈5), keeping the wing
   widths fixed. Keep the combinations that pass the rules and meet the
   target. Rank them by how far they are from the requested anchors (the
   smallest total deviation wins). The search is brute force, which is fine
   at this size (K^legs, at most 4 legs). The screener builders already work
   this way.
5. **Response**: the best match, the next 3–5 alternatives, and a `reasons`
   list when nothing qualifies (e.g. "No 16Δ call with a bid/ask", or "Best
   credit found $0.82 < $1.00 target").

Per-candidate metrics come from the shared math moved out of the screener,
at mid prices:
net credit or debit, max profit, max loss, breakevens, ROI and annualized
ROI (credit) or reward-to-risk (debit), net Δ, per-leg Δ and IV, and a rough
POP (1 − |short Δ|, or 1 − Σ|short Δs| for two-sided risk; Δ-based for
debit; labeled as an estimate). For uncapped losses (naked short call,
straddle, strangle), max loss shows as "Unlimited" instead of a number.

Futures roots (`/ES`): follow the leading-slash convention from end to end.
Dollar figures use the futures multiplier (`contractMultiplier`).

### API

- `GET /api/market/strategies`: the template list (id, name, direction,
  legs, default params, which parameters apply). This is the **single
  source of truth** for the overlay form and the copilot tool.
- `POST /api/market/strategy/build`, body
  `{symbol, expirationDate, strategy, params}` → `{spot, iv, dte,
  expirationDate, best, alternatives, reasons}`. It is read-only, uses
  `Depends(require_auth)`, and gets a 422 on bad input (same style as the
  screener route). Add matching functions in `frontend/src/api/client.js`.

### Refactor first

Move `_intrinsic`, `_payoff`, `_leg`, and `_position_row` from
`screener_strategies.py` into `service/strategy_math.py`, and add mid pricing
and debit handling there. Make the screener import them. Check that the
Ratio Put / Jade Lizard screener output is unchanged by running a one-off
script before and after the move.

## Frontend: overlay on Analyze

### Entry point

- Add a **"Build Strategy"** button in Analyze's header row, next to the
  `Price` badge. It is **disabled until a ticker is loaded**, meaning there
  is a symbol and its expirations are loaded. The tooltip then says "Enter a
  symbol first".
- Clicking it opens `components/StrategyBuilderOverlay.jsx`. This keeps the
  builder out of `StrikeLab.jsx`, which is already 1,600+ lines. Props:
  `symbol`, `spot`, `expirations`, `initialExpIndex`, `hasLegs`, `onApply`,
  `onClose`.

### Overlay layout

- A backdrop with a centered panel, styled from the landing overlay pattern
  (generalized to a shared class). Esc or a click on the backdrop closes it.
  On narrow screens it is full-screen, with no horizontal scroll.
- **Header**: ticker + spot (read-only, since the ticker is chosen on
  Analyze), and the **Net Credit / Net Debit** switch (`.tab-row`).
- **Step 1, strategy**: cards for the selected direction, each with a small
  payoff-shape sketch (inline SVG, token colors) and a one-line description.
- **Step 2, parameters**: expiration pills, then a form built from the
  template: an anchor-mode switch for each leg group, the delta/%/σ/width
  inputs, contracts, and the credit or debit target. Field explanations use
  `HelpTip`.
- **Build**. The solver runs on demand, not on every quote tick, so the
  legs stay put while the user reads them.
- **Step 3, result**:
  - A legs table that uses `optionSymbol.js` for contract labels and shows
    Δ, IV, bid/ask/mid.
  - Metric tiles: net credit/debit, max profit, max loss, breakevens, POP
    estimate, ROI or reward-to-risk.
  - Alternatives as a small `DataTable`. Clicking one selects it.
  - **"Apply"** (primary button). If Analyze already has legs, its tooltip
    says they will be replaced.
- The overlay's last strategy, direction and params are kept in a
  `createSessionCache()` cache, so reopening it starts where the user left
  off. The cache is cleared on logout.

### Applying to Analyze

- Turn the copilot `apply()` logic in `StrikeLab.jsx` into a named
  `applyLegs(incomingLegs, { strategy })`. It does four things: replaces the
  legs, sets `pendingExp` to the built expiration, sets `fitRangeToLegsRef`,
  and stores the strategy label. Both the copilot Apply and the builder's
  `onApply` call it. The builder never changes the symbol, because the
  overlay is opened for the ticker already selected.
- Analyze shows a **strategy badge** above the legs editor, e.g. "Iron
  Condor · 16Δ · $5 wings · $1.42 credit". It clears once the user adds or
  removes a leg or changes a leg's strike, side or type. It is included in
  Analyze's `setCopilotContext("StrikeLab", …)`, so the copilot knows what
  the position is meant to be.

## Copilot (later phase)

- Add a `build_strategy` tool in `copilot/tools.py` that wraps
  `MarketService.build_strategy`, plus its hand-written schema in
  `TOOL_SCHEMAS`. It is read-only. Its output feeds the existing "Apply"
  flow.
- **Conflict to resolve**: `copilot/agent.py` has a hard **net-credit-only**
  rule. The builder UI offering debit strategies is fine. The copilot tool,
  though, should be limited to `direction="credit"` unless that rule is
  deliberately changed.
- Add the missing skill docs: `straddle.md`, `jade_lizard.md`,
  `credit_spreads.md`, `iron_butterfly.md`, and debit docs only if the
  copilot rule changes.

## Guardrails

- **No order placement.** There is no "Trade" or "Send order" button. Never
  touch `TastytradeClient.place_order` or `cancel_order`. The builder only
  proposes, and Analyze only displays.
- New colors (overlay backdrop, badge, cards) go through `tokens.css`, in
  both the light and dark blocks.
- This is market data only, so it needs no Schwab guard. With
  `CHAIN_PROVIDER=schwab` the chain call runs under the requesting user's
  token context through `require_auth`. Don't start a thread pool in the
  solver. If you ever do, use `contextvars.copy_context().run`.

## Phases

1. **Backend core**: the `strategy_math.py` refactor (check the screener
   output is unchanged), mid pricing and debit handling, all templates, the
   delta and % OTM anchors, the solver without target search, and both
   endpoints. Check with a one-off script on SPY, a stock, and `/ES`.
2. **Overlay and apply**: the "Build Strategy" button, the overlay (direction
   switch, strategy cards, form, result), extracting `applyLegs`, and the
   strategy badge on Analyze. Extract `ExpirationPills` if the overlay needs
   its own pills.
3. **Solver depth**: credit/debit target search, alternatives,
   expected-move (σ) anchor, and wing-by-delta.
4. **Copilot and docs**: the `build_strategy` tool (credit-only unless the
   rule changes) and the new skill docs.
5. **Nice-to-haves**: saved presets per user (SQLite, alongside `users.py`),
   multi-expiration templates (calendars and diagonals, which Analyze only
   partly supports), and a "Build similar" action from Screener rows.
