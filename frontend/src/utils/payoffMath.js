/* Option payoff math for the Analyze page (StrikeLab), kept out of the
 * component so it can be tested (payoffMath.test.js, `npm test`). The
 * expiration figures — breakevens, max profit/loss, probability of profit —
 * must agree with service/shared/strategy_math.py; both are checked against
 * the same cases in tests/fixtures/payoff_cases.json.
 *
 * A leg: { type: "PUT"|"CALL", side: "BUY"|"SELL", strike, premium, qty,
 *          multiplier? } — qty unsigned, P&L in dollars (x multiplier). */

import { MULTIPLIER } from "./contractMultiplier.js";

// Abramowitz-Stegun 7.1.26 — accurate to ~1.5e-7, plenty for pricing here.
export function erf(x) {
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return sign * y;
}
export function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

// Real Black-Scholes (no dividend yield, r=0 — same no-rate assumption the
// old heuristic made, and matches OptionStrat closely enough over a
// days-to-expiration window that carry cost is negligible either way).
export function blackScholes(spot, strike, dte, iv, isCall) {
  const t = Math.max(dte / 365, 1 / 365);
  const intrinsic = isCall ? Math.max(0, spot - strike) : Math.max(0, strike - spot);
  if (iv <= 0) return Math.max(0.01, intrinsic);
  const sqrtT = Math.sqrt(t);
  const d1 = (Math.log(spot / strike) + (iv * iv / 2) * t) / (iv * sqrtT);
  const d2 = d1 - iv * sqrtT;
  const value = isCall
    ? spot * normCdf(d1) - strike * normCdf(d2)
    : strike * normCdf(-d2) - spot * normCdf(-d1);
  return Math.max(0.01, value);
}

/* ============================================================================
   PAYOFF MATH
============================================================================ */

export function legPL(leg, price) {
  const intrinsic =
    leg.type === "CALL" ? Math.max(0, price - leg.strike) : Math.max(0, leg.strike - price);
  const perShare = leg.side === "BUY" ? intrinsic - leg.premium : leg.premium - intrinsic;
  return perShare * leg.qty * (leg.multiplier ?? MULTIPLIER);
}

export function totalPL(legs, price) {
  return legs.reduce((sum, leg) => sum + legPL(leg, price), 0);
}

export function netCredit(legs) {
  return legs.reduce(
    (sum, leg) => sum + (leg.side === "SELL" ? 1 : -1) * leg.premium * leg.qty * (leg.multiplier ?? MULTIPLIER),
    0
  );
}

// The expiration payoff is piecewise linear with kinks only at the strikes,
// so it's evaluated exactly at price 0 and each strike, plus the slope past
// the highest strike — no price-grid sampling (which can miss a sharp peak,
// e.g. a ratio spread's). Same method as strategy_math.payoff_profile.
export function payoffProfile(legs) {
  const points = [0, ...[...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b)];
  const values = points.map((p) => totalPL(legs, p));
  const slope = upsideSlope(legs);
  const breakevens = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [p1, v1, p2, v2] = [points[i], values[i], points[i + 1], values[i + 1]];
    if (((v1 < 0 && v2 >= 0) || (v1 >= 0 && v2 < 0)) && v1 !== v2) breakevens.push(p1 + ((p2 - p1) * -v1) / (v2 - v1));
  }
  const last = values[values.length - 1];
  if (slope && ((last < 0 && slope > 0) || (last > 0 && slope < 0))) breakevens.push(points[points.length - 1] - last / slope);
  return {
    maxProfit: slope > 0 ? Infinity : Math.max(...values),
    maxLoss: slope < 0 ? -Infinity : Math.min(...values),
    breakevens,
  };
}

/** Breakeven prices at expiration, rounded to the cent. */
export function findBreakevens(legs) {
  return payoffProfile(legs).breakevens.map((b) => +b.toFixed(2));
}

/** Theoretical (pre-expiration) P&L for one leg, using the same lightweight
 *  Black-Scholes approximation the mock chain is built from. At dte<=0 this
 *  collapses to pure intrinsic value, matching the at-expiration payoff. */
export function legTheoPL(leg, price, dte, iv) {
  if (dte <= 0) return legPL(leg, price);
  const value = blackScholes(price, leg.strike, dte, iv, leg.type === "CALL");
  const perShare = leg.side === "BUY" ? value - leg.premium : leg.premium - value;
  return perShare * leg.qty * (leg.multiplier ?? MULTIPLIER);
}

export function totalTheoPL(legs, price, dte, iv) {
  return legs.reduce((sum, leg) => sum + legTheoPL(leg, price, dte, iv), 0);
}

/** { maxProfit, maxLoss } at expiration, in dollars: Infinity / -Infinity
 *  when unbounded (net long / net short calls past the highest strike). */
export function maxLossProfit(legs) {
  const { maxProfit, maxLoss } = payoffProfile(legs);
  return { maxProfit, maxLoss };
}

// Net calls held, multiplier-weighted: the P&L slope past the highest
// strike. > 0 = unlimited profit to the upside, < 0 = unlimited loss.
export function upsideSlope(legs) {
  return legs.reduce(
    (sum, leg) =>
      leg.type === "CALL" ? sum + (leg.side === "BUY" ? 1 : -1) * leg.qty * (leg.multiplier ?? MULTIPLIER) : sum,
    0
  );
}

/** Estimated chance the position finishes above zero P&L at expiration,
 *  under a driftless lognormal model at volatility `iv` (a fraction) — the
 *  same model the Strategy Builder uses (service/shared/strategy_math.py's
 *  probability_of_profit), so the two pages agree. The breakevens split the
 *  price axis into regions of constant sign; each profitable region adds its
 *  probability. Null without legs, a spot or an IV. */
export function probabilityOfProfit(legs, spot, iv, dte, breakevens) {
  if (legs.length === 0 || !(spot > 0) || !(iv > 0)) return null;
  const sigma = iv * Math.sqrt(Math.max(dte ?? 0, 0.5) / 365);
  const cdf = (p) => (p <= 0 ? 0 : normCdf((Math.log(p / spot) + (sigma * sigma) / 2) / sigma));
  const edges = [0, ...[...breakevens].sort((a, b) => a - b), Infinity];
  const top = Math.max(...legs.map((l) => l.strike));
  let pop = 0;
  for (let i = 0; i < edges.length - 1; i++) {
    const lo = edges[i];
    const hi = edges[i + 1];
    const probe = hi === Infinity ? Math.max(lo, top) * 1.5 + 1 : (lo + hi) / 2;
    if (totalPL(legs, probe) > 0) pop += (hi === Infinity ? 1 : cdf(hi)) - cdf(lo);
  }
  return pop;
}
