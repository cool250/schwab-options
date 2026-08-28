import React, { useState, useMemo, useCallback, useEffect, useRef } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  Tooltip,
} from "recharts";
import { getOptionChain } from "../api/client";

function blackScholesApprox(spot, strike, dte, iv, isCall) {
  const t = Math.max(dte / 365, 1 / 365);
  const moneyness = (spot - strike) / (spot * iv * Math.sqrt(t));
  const intrinsic = isCall ? Math.max(0, spot - strike) : Math.max(0, strike - spot);
  const timeValue = spot * iv * Math.sqrt(t) * 0.4 * Math.exp(-0.5 * moneyness * moneyness);
  return Math.max(0.01, intrinsic + timeValue);
}

/* ============================================================================
   PAYOFF MATH
============================================================================ */

const MULTIPLIER = 100;

function legPL(leg, price) {
  const intrinsic =
    leg.type === "CALL" ? Math.max(0, price - leg.strike) : Math.max(0, leg.strike - price);
  const perShare = leg.side === "BUY" ? intrinsic - leg.premium : leg.premium - intrinsic;
  return perShare * leg.qty * MULTIPLIER;
}

function totalPL(legs, price) {
  return legs.reduce((sum, leg) => sum + legPL(leg, price), 0);
}

function netCredit(legs) {
  return legs.reduce(
    (sum, leg) => sum + (leg.side === "SELL" ? 1 : -1) * leg.premium * leg.qty * MULTIPLIER,
    0
  );
}

function findBreakevens(legs, lo, hi) {
  const steps = 4000;
  const pts = [];
  let prevPrice = lo;
  let prevPL = totalPL(legs, lo);
  for (let i = 1; i <= steps; i++) {
    const price = lo + ((hi - lo) * i) / steps;
    const pl = totalPL(legs, price);
    if ((prevPL < 0 && pl >= 0) || (prevPL > 0 && pl <= 0)) {
      const t = prevPL === pl ? 0 : -prevPL / (pl - prevPL);
      pts.push(+(prevPrice + t * (price - prevPrice)).toFixed(2));
    }
    prevPrice = price;
    prevPL = pl;
  }
  return pts;
}

/** Theoretical (pre-expiration) P&L for one leg, using the same lightweight
 *  Black-Scholes approximation the mock chain is built from. At dte<=0 this
 *  collapses to pure intrinsic value, matching the at-expiration payoff. */
function legTheoPL(leg, price, dte, iv) {
  if (dte <= 0) return legPL(leg, price);
  const value = blackScholesApprox(price, leg.strike, dte, iv, leg.type === "CALL");
  const perShare = leg.side === "BUY" ? value - leg.premium : leg.premium - value;
  return perShare * leg.qty * MULTIPLIER;
}

function totalTheoPL(legs, price, dte, iv) {
  return legs.reduce((sum, leg) => sum + legTheoPL(leg, price, dte, iv), 0);
}

/** Builds the strike x date P&L grid used by the Table view. */
function buildPLTable(legs, spot, lo, hi, maxDte, iv, rows = 16, cols = 8) {
  const step = (hi - lo) / (rows - 1);
  const prices = Array.from({ length: rows }, (_, i) => +(hi - i * step).toFixed(2));

  const dteSteps = [];
  for (let i = 0; i < cols; i++) {
    const dte = Math.round(maxDte - (maxDte * i) / (cols - 1));
    dteSteps.push(i === cols - 1 ? 0 : dte);
  }
  const uniqueDte = [...new Set(dteSteps)].sort((a, b) => b - a);

  const grid = prices.map((price) => ({
    price,
    values: uniqueDte.map((dte) => totalTheoPL(legs, price, dte, iv)),
  }));
  return { dteCols: uniqueDte, grid };
}

function maxLossProfit(legs, lo, hi) {
  const steps = 2000;
  let maxP = -Infinity;
  let minP = Infinity;
  for (let i = 0; i <= steps; i++) {
    const price = lo + ((hi - lo) * i) / steps;
    const pl = totalPL(legs, price);
    if (pl > maxP) maxP = pl;
    if (pl < minP) minP = pl;
  }
  // Naked short legs make loss unbounded toward zero (puts) — check the low edge explicitly.
  const lowEdgePL = totalPL(legs, lo);
  if (lowEdgePL < minP) minP = lowEdgePL;
  return { maxProfit: maxP, maxLoss: minP };
}

/* ============================================================================
   DEFAULT STRATEGY — Jade Lizard on SPY, matches the reference build exactly
============================================================================ */

const DEFAULT_SYMBOL = "SPY";
const DEFAULT_SPOT = 766.01;
const DEFAULT_LEGS = [
  { id: "l1", side: "SELL", qty: 1, type: "PUT", strike: 764, premium: 9.2, dte: 13 },
  { id: "l2", side: "SELL", qty: 1, type: "CALL", strike: 769, premium: 3.1, dte: 13 },
  { id: "l3", side: "BUY", qty: 1, type: "CALL", strike: 775, premium: 4.815, dte: 13 },
];

const EXPIRATIONS = [
  { label: "27", month: "Aug", dte: 4 },
  { label: "28", month: "Aug", dte: 5 },
  { label: "31", month: "Aug", dte: 8 },
  { label: "1", month: "Sep", dte: 9 },
  { label: "2", month: "Sep", dte: 10 },
  { label: "4", month: "Sep", dte: 12 },
  { label: "8", month: "Sep", dte: 13 },
  { label: "9", month: "Sep", dte: 17 },
  { label: "11", month: "Sep", dte: 19 },
  { label: "18", month: "Sep", dte: 26 },
  { label: "25", month: "Sep", dte: 33 },
  { label: "30", month: "Sep", dte: 38 },
];

/* ============================================================================
   UI PRIMITIVES
============================================================================ */

const fmtMoney = (n, opts = {}) => {
  const abs = Math.abs(n);
  const s = abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "-" : ""}$${s}`;
};

function Metric({ label, value, tone, icon, sub }) {
  return (
    <div className="sl-metric">
      <div className="sl-metric-label">
        <span className="sl-metric-icon">{icon}</span>
        {label}
      </div>
      <div className={`sl-metric-value tone-${tone || "flat"}`}>{value}</div>
      {sub && <div className="sl-metric-sub">{sub}</div>}
    </div>
  );
}

/* ============================================================================
   MAIN APP
============================================================================ */

export default function StrikeLab() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [symbolInput, setSymbolInput] = useState(DEFAULT_SYMBOL);
  const [spot, setSpot] = useState(DEFAULT_SPOT);
  const [expIndex, setExpIndex] = useState(6); // "8 Sep" selected, matches reference
  const [legs, setLegs] = useState(DEFAULT_LEGS);
  const [rangePct, setRangePct] = useState(3.6);
  const [ivPct, setIvPct] = useState(10.9);
  const [chain, setChain] = useState(null);
  const [loadingChain, setLoadingChain] = useState(false);
  const [strategyName, setStrategyName] = useState("Jade Lizard");
  const [view, setView] = useState("graph"); // 'graph' | 'table'

  const dte = EXPIRATIONS[expIndex].dte;

  const loadChain = useCallback(async () => {
    setLoadingChain(true);
    try {
      const result = await getOptionChain(symbol, dte);
      if (result && result.chain) {
        setChain(result);
        setSpot(result.spot);
        setIvPct(result.iv * 100);
      } else {
        setChain(null);
      }
    } catch (e) {
      setChain(null);
    } finally {
      setLoadingChain(false);
    }
  }, [symbol, dte]);

  useEffect(() => {
    loadChain();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, dte]);

  const lo = spot * (1 - rangePct / 100);
  const hi = spot * (1 + rangePct / 100);

  const chartData = useMemo(() => {
    const points = 140;
    const data = [];
    for (let i = 0; i <= points; i++) {
      const price = lo + ((hi - lo) * i) / points;
      const pl = totalPL(legs, price);
      data.push({
        price: +price.toFixed(2),
        pos: pl >= 0 ? pl : 0,
        neg: pl < 0 ? pl : 0,
        pl,
      });
    }
    return data;
  }, [legs, lo, hi]);

  const credit = useMemo(() => netCredit(legs), [legs]);
  const { maxProfit, maxLoss } = useMemo(
    () => maxLossProfit(legs, Math.max(0.01, spot * 0.01), spot * 4),
    [legs, spot]
  );
  const breakevens = useMemo(
    () => findBreakevens(legs, Math.max(0.01, spot * 0.01), spot * 4),
    [legs, spot]
  );

  const updateLeg = (id, patch) =>
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  const removeLeg = (id) => setLegs((prev) => prev.filter((l) => l.id !== id));

  const addLeg = () => {
    const nearestStrike = chain
      ? chain.chain.reduce((a, b) =>
          Math.abs(b.strikePrice - spot) < Math.abs(a.strikePrice - spot) ? b : a
        ).strikePrice
      : Math.round(spot);
    setLegs((prev) => [
      ...prev,
      {
        id: `l${Date.now()}`,
        side: "SELL",
        qty: 1,
        type: "PUT",
        strike: nearestStrike,
        premium: 1.0,
        dte,
      },
    ]);
  };

  const addLegFromChain = (type, side, strike, premium) => {
    setLegs((prev) => [
      ...prev,
      { id: `l${Date.now()}`, side, qty: 1, type, strike, premium: +premium.toFixed(2), dte },
    ]);
  };

  const submitSymbol = (e) => {
    e.preventDefault();
    const s = symbolInput.trim().toUpperCase();
    if (s) setSymbol(s);
  };

  return (
    <div className="sl-root">
      <style>{CSS}</style>

      {/* ---------------- Header ---------------- */}
      <header className="sl-header">
        <div className="sl-brand">
          <div className="sl-brand-mark">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d="M3 17 L9 9 L14 13 L21 4" stroke="#F0A868" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="21" cy="4" r="2.1" fill="#F0A868" />
            </svg>
          </div>
          <div>
            <div className="sl-brand-name">StrikeLab</div>
            <div className="sl-brand-sub">live chain via Schwab market data</div>
          </div>
        </div>
      </header>

      {/* ---------------- Symbol / strategy row ---------------- */}
      <div className="sl-titlebar">
        <input
          className="sl-strategy-name"
          value={strategyName}
          onChange={(e) => setStrategyName(e.target.value)}
        />
        <span className="sl-legcount">{legs.length} legs</span>
      </div>

      <div className="sl-symbolbar">
        <form onSubmit={submitSymbol} className="sl-symbol-form">
          <input
            className="sl-symbol-input"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
          />
        </form>
        <div className="sl-price">
          <span className="sl-price-value">${spot.toFixed(2)}</span>
          <span className="sl-price-change">+0.01% · +$0.10</span>
        </div>
        {loadingChain && <span className="sl-loading-tag">syncing chain…</span>}
      </div>

      {/* ---------------- Expirations ---------------- */}
      <div className="sl-exp-label">EXPIRATION · {dte}d</div>
      <div className="sl-exp-row">
        {EXPIRATIONS.map((e, i) => (
          <button
            key={i}
            className={`sl-exp-pill ${i === expIndex ? "active" : ""}`}
            onClick={() => setExpIndex(i)}
          >
            <span className="sl-exp-month">{e.month}</span>
            <span className="sl-exp-day">{e.label}</span>
          </button>
        ))}
      </div>

      {/* ---------------- Strike ruler ---------------- */}
      <StrikeRuler legs={legs} spot={spot} lo={lo} hi={hi} />

      {/* ---------------- Metrics ---------------- */}
      <div className="sl-metrics">
        <Metric
          label="NET CREDIT"
          icon="◆"
          tone={credit >= 0 ? "up" : "down"}
          value={fmtMoney(Math.abs(credit))}
        />
        <Metric label="MAX LOSS" icon="▾" tone="down" value={fmtMoney(Math.abs(maxLoss))} />
        <Metric label="MAX PROFIT" icon="▴" tone="up" value={fmtMoney(Math.abs(maxProfit))} />
        <Metric
          label="BREAKEVEN"
          icon="→"
          tone="flat"
          value={
            breakevens.length
              ? breakevens.map((b) => `$${b.toFixed(2)}`).join(" / ")
              : "None in range"
          }
          sub={
            breakevens.length
              ? `${(((breakevens[0] - spot) / spot) * 100).toFixed(1)}% from spot`
              : null
          }
        />
      </div>

      {/* ---------------- Chart / Table ---------------- */}
      {view === "graph" ? (
        <div className="sl-chart-wrap">
          <ResponsiveContainer width="100%" height={340}>
            <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="slPos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3DDC97" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="#3DDC97" stopOpacity={0.03} />
                </linearGradient>
                <linearGradient id="slNeg" x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stopColor="#FF5D5D" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="#FF5D5D" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1D2333" vertical={false} />
              <XAxis
                dataKey="price"
                type="number"
                domain={[lo, hi]}
                tickFormatter={(v) => `$${Math.round(v)}`}
                stroke="#535A6E"
                tick={{ fontSize: 11, fontFamily: "var(--sl-mono)" }}
                tickLine={false}
                axisLine={{ stroke: "#232838" }}
              />
              <YAxis
                tickFormatter={(v) => (v === 0 ? "$0" : `${v > 0 ? "+" : ""}${v}`)}
                stroke="#535A6E"
                tick={{ fontSize: 11, fontFamily: "var(--sl-mono)" }}
                tickLine={false}
                axisLine={false}
                width={56}
              />
              <Tooltip content={<SLTooltip />} />
              <ReferenceLine y={0} stroke="#3A4056" strokeWidth={1.5} />
              <ReferenceLine x={spot} stroke="#F0A868" strokeDasharray="3 4" strokeWidth={1.5} />
              {breakevens.map((b, i) => (
                <ReferenceLine key={i} x={b} stroke="#5B8DEF" strokeWidth={1.2} />
              ))}
              <Area
                dataKey="pos"
                stroke="#3DDC97"
                strokeWidth={2}
                fill="url(#slPos)"
                isAnimationActive={true}
                animationDuration={700}
                dot={false}
              />
              <Area
                dataKey="neg"
                stroke="#FF5D5D"
                strokeWidth={2}
                fill="url(#slNeg)"
                isAnimationActive={true}
                animationDuration={700}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
          <div className="sl-chart-caption">Payoff shown at expiration · {dte} days out</div>
        </div>
      ) : view === "table" ? (
        <PLTable
          legs={legs}
          spot={spot}
          lo={lo}
          hi={hi}
          dte={dte}
          iv={ivPct / 100}
          maxProfit={maxProfit}
          maxLoss={maxLoss}
        />
      ) : (
        <OptionChainTable
          chain={chain}
          spot={spot}
          loading={loadingChain}
          onAddLeg={addLegFromChain}
        />
      )}

      {/* ---------------- Range / IV sliders ---------------- */}
      <div className="sl-sliderrow">
        <span className="sl-slider-label">RANGE ±{rangePct.toFixed(1)}%</span>
        <input
          type="range"
          min="0.5"
          max="15"
          step="0.1"
          value={rangePct}
          onChange={(e) => setRangePct(+e.target.value)}
          className="sl-slider"
        />
      </div>
      <div className="sl-sliderrow">
        <span className="sl-slider-label">IMPLIED VOL {ivPct.toFixed(1)}%</span>
        <input
          type="range"
          min="2"
          max="60"
          step="0.1"
          value={ivPct}
          onChange={(e) => setIvPct(+e.target.value)}
          className="sl-slider"
        />
      </div>

      {/* ---------------- View tabs ---------------- */}
      <div className="sl-tabs">
        {[
          { id: "chain", label: "≡ Chain" },
          { id: "table", label: "▤ Table" },
          { id: "graph", label: "☁ Graph" },
        ].map((t) => (
          <button
            key={t.id}
            className={`sl-tab ${view === t.id ? "active" : ""}`}
            onClick={() => setView(t.id)}
          >
            {t.label}
          </button>
        ))}
        {["Profit / Loss %", "Contract Value", "% of Max Risk"].map((label) => (
          <button key={label} className="sl-tab sl-tab-disabled" disabled title="Not built yet">
            {label}
          </button>
        ))}
      </div>

      {/* ---------------- Legs table ---------------- */}
      <div className="sl-legs">
        <div className="sl-legs-header">
          <span>POSITIONS</span>
          <button className="sl-add-btn" onClick={addLeg}>
            + Add leg
          </button>
        </div>
        <div className="sl-legs-table">
          <div className="sl-legs-row sl-legs-row-head">
            <span>Side</span>
            <span>Qty</span>
            <span>Type</span>
            <span>Strike</span>
            <span>Premium</span>
            <span></span>
          </div>
          {legs.map((leg) => (
            <div className="sl-legs-row" key={leg.id}>
              <select
                className={`sl-cell sl-side sl-side-${leg.side.toLowerCase()}`}
                value={leg.side}
                onChange={(e) => updateLeg(leg.id, { side: e.target.value })}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
              <input
                className="sl-cell sl-qty"
                type="number"
                min="1"
                value={leg.qty}
                onChange={(e) => updateLeg(leg.id, { qty: Math.max(1, +e.target.value) })}
              />
              <select
                className={`sl-cell sl-type sl-type-${leg.type.toLowerCase()}`}
                value={leg.type}
                onChange={(e) => updateLeg(leg.id, { type: e.target.value })}
              >
                <option value="CALL">CALL</option>
                <option value="PUT">PUT</option>
              </select>
              <input
                className="sl-cell sl-strike"
                type="number"
                step="0.5"
                value={leg.strike}
                onChange={(e) => updateLeg(leg.id, { strike: +e.target.value })}
              />
              <input
                className="sl-cell sl-premium"
                type="number"
                step="0.01"
                value={leg.premium}
                onChange={(e) => updateLeg(leg.id, { premium: Math.max(0, +e.target.value) })}
              />
              <button className="sl-remove-btn" onClick={() => removeLeg(leg.id)} title="Remove leg">
                ×
              </button>
            </div>
          ))}
          {legs.length === 0 && (
            <div className="sl-legs-empty">No legs yet — add one to start building a payoff.</div>
          )}
        </div>
      </div>

      <footer className="sl-footer">
        Simplified intrinsic-value model at expiration · not investment advice
      </footer>
    </div>
  );
}

/* ============================================================================
   Strike ruler — horizontal number line with leg markers, echoes the source UI
============================================================================ */
function StrikeRuler({ legs, spot, lo, hi }) {
  const width = 100;
  const pct = (price) => ((price - lo) / (hi - lo)) * width;
  const ticks = [];
  const tickStep = (hi - lo) / 8;
  for (let i = 0; i <= 8; i++) ticks.push(lo + i * tickStep);

  return (
    <div className="sl-ruler">
      <div className="sl-ruler-label">STRIKES</div>
      <div className="sl-ruler-track">
        <div className="sl-ruler-line" />
        {ticks.map((t, i) => (
          <div key={i} className="sl-ruler-tick" style={{ left: `${pct(t)}%` }}>
            <span>${Math.round(t)}</span>
          </div>
        ))}
        <div className="sl-ruler-spot" style={{ left: `${pct(spot)}%` }}>
          <span className="sl-ruler-spot-label">SPOT</span>
          <span className="sl-ruler-spot-arrow">▾</span>
        </div>
        {legs.map((leg) => (
          <div
            key={leg.id}
            className={`sl-ruler-tag ${leg.side === "SELL" ? "tag-sell" : "tag-buy"} tag-${leg.type.toLowerCase()}`}
            style={{ left: `${pct(leg.strike)}%` }}
          >
            {leg.strike}
            {leg.type[0]}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ============================================================================
   Table view — strike x date theta-decay heatmap
============================================================================ */
function cellColor(value, maxProfit, maxLoss) {
  if (value >= 0) {
    const t = maxProfit > 0 ? Math.min(1, value / maxProfit) : 0;
    const alpha = 0.12 + t * 0.68;
    return { background: `rgba(61, 220, 151, ${alpha})`, color: t > 0.45 ? "#04150D" : "#BFF3DA" };
  }
  const t = maxLoss < 0 ? Math.min(1, value / maxLoss) : 0;
  const alpha = 0.12 + t * 0.68;
  return { background: `rgba(255, 93, 93, ${alpha})`, color: t > 0.45 ? "#210404" : "#FFD3D3" };
}

function dteToLabel(dte, todayDte) {
  if (dte === 0) return "Exp";
  if (dte === todayDte) return "Today";
  return `${dte}d`;
}

function PLTable({ legs, spot, lo, hi, dte, iv, maxProfit, maxLoss }) {
  const { dteCols, grid } = useMemo(
    () => buildPLTable(legs, spot, lo, hi, dte, iv, 16, 8),
    [legs, spot, lo, hi, dte, iv]
  );
  const spotRowIdx = grid.reduce(
    (best, row, i) =>
      Math.abs(row.price - spot) < Math.abs(grid[best].price - spot) ? i : best,
    0
  );

  return (
    <div className="sl-table-wrap">
      <div className="sl-ptable" style={{ gridTemplateColumns: `70px repeat(${dteCols.length}, 1fr)` }}>
        <div className="sl-ptable-cell sl-ptable-corner">Strike</div>
        {dteCols.map((d, i) => (
          <div key={i} className="sl-ptable-cell sl-ptable-colhead">
            {dteToLabel(d, dte)}
          </div>
        ))}
        {grid.map((row, ri) => (
          <React.Fragment key={ri}>
            <div className={`sl-ptable-cell sl-ptable-strike ${ri === spotRowIdx ? "sl-ptable-spotrow" : ""}`}>
              ${row.price.toFixed(0)}
            </div>
            {row.values.map((v, ci) => {
              const style = cellColor(v, maxProfit, maxLoss);
              return (
                <div
                  key={ci}
                  className={`sl-ptable-cell sl-ptable-val ${ri === spotRowIdx ? "sl-ptable-spotrow" : ""}`}
                  style={{ background: style.background, color: style.color }}
                >
                  {v >= 0 ? "+" : ""}
                  {Math.round(v)}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
      <div className="sl-chart-caption">
        Theoretical value pre-expiration (IV {(iv * 100).toFixed(1)}%) · intrinsic value at "Exp"
      </div>
    </div>
  );
}

/* ============================================================================
   Option chain view — standard Calls | Strike | Puts table around ATM
============================================================================ */
const CHAIN_RADIUS = 8; // strikes shown on each side of ATM

function OptionChainTable({ chain, spot, loading, onAddLeg }) {
  const rows = chain?.chain;

  if (!rows || rows.length === 0) {
    return (
      <div className="sl-table-wrap">
        <div className="sl-chain-empty">
          {loading ? "Loading option chain…" : "No option chain available for this symbol/expiration."}
        </div>
      </div>
    );
  }

  const sorted = [...rows].sort((a, b) => a.strikePrice - b.strikePrice);
  const atmIdx = sorted.reduce(
    (best, row, i) =>
      Math.abs(row.strikePrice - spot) < Math.abs(sorted[best].strikePrice - spot) ? i : best,
    0
  );
  const start = Math.max(0, atmIdx - CHAIN_RADIUS);
  const end = Math.min(sorted.length, atmIdx + CHAIN_RADIUS + 1);
  const visible = sorted.slice(start, end);
  const atmStrike = sorted[atmIdx].strikePrice;

  return (
    <div className="sl-table-wrap">
      <div className="sl-chain">
        <div className="sl-chain-row sl-chain-head">
          <span className="sl-chain-side-label" style={{ gridColumn: "1 / 4" }}>CALLS</span>
          <span style={{ gridColumn: "4 / 5" }} />
          <span className="sl-chain-side-label" style={{ gridColumn: "5 / 8" }}>PUTS</span>
        </div>
        <div className="sl-chain-row sl-chain-subhead">
          <span>Delta</span>
          <span>Bid</span>
          <span>Ask</span>
          <span>Strike</span>
          <span>Bid</span>
          <span>Ask</span>
          <span>Delta</span>
        </div>
        {visible.map((row) => {
          const isAtm = row.strikePrice === atmStrike;
          return (
            <div key={row.strikePrice} className={`sl-chain-row ${isAtm ? "sl-chain-atm" : ""}`}>
              <span className="sl-chain-delta">{row.call ? row.call.delta.toFixed(2) : "—"}</span>
              <span
                className={`sl-chain-bid ${row.call ? "" : "sl-chain-disabled"}`}
                onClick={() => row.call && onAddLeg("CALL", "SELL", row.strikePrice, row.call.bid)}
                title={row.call ? "Sell a call at bid" : undefined}
              >
                {row.call ? row.call.bid.toFixed(2) : "—"}
              </span>
              <span
                className={`sl-chain-ask ${row.call ? "" : "sl-chain-disabled"}`}
                onClick={() => row.call && onAddLeg("CALL", "BUY", row.strikePrice, row.call.ask)}
                title={row.call ? "Buy a call at ask" : undefined}
              >
                {row.call ? row.call.ask.toFixed(2) : "—"}
              </span>
              <span className="sl-chain-strike">{row.strikePrice}</span>
              <span
                className={`sl-chain-bid ${row.put ? "" : "sl-chain-disabled"}`}
                onClick={() => row.put && onAddLeg("PUT", "SELL", row.strikePrice, row.put.bid)}
                title={row.put ? "Sell a put at bid" : undefined}
              >
                {row.put ? row.put.bid.toFixed(2) : "—"}
              </span>
              <span
                className={`sl-chain-ask ${row.put ? "" : "sl-chain-disabled"}`}
                onClick={() => row.put && onAddLeg("PUT", "BUY", row.strikePrice, row.put.ask)}
                title={row.put ? "Buy a put at ask" : undefined}
              >
                {row.put ? row.put.ask.toFixed(2) : "—"}
              </span>
              <span className="sl-chain-delta">{row.put ? row.put.delta.toFixed(2) : "—"}</span>
            </div>
          );
        })}
      </div>
      <div className="sl-chart-caption">Click a bid to sell, an ask to buy · {visible.length} strikes around spot</div>
    </div>
  );
}

function SLTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const pl = payload[0].payload.pl;
  return (
    <div className="sl-tooltip">
      <div className="sl-tooltip-price">${(+label).toFixed(2)}</div>
      <div className={`sl-tooltip-pl ${pl >= 0 ? "tone-up" : "tone-down"}`}>
        {pl >= 0 ? "+" : ""}
        {fmtMoney(pl)}
      </div>
    </div>
  );
}

/* ============================================================================
   STYLES
============================================================================ */
const CSS = `
:root {
  --sl-void: #0A0D14;
  --sl-panel: #11151F;
  --sl-panel-2: #161B28;
  --sl-border: #232838;
  --sl-text: #E8EAF0;
  --sl-muted: #6E7690;
  --sl-amber: #F0A868;
  --sl-up: #3DDC97;
  --sl-down: #FF5D5D;
  --sl-blue: #5B8DEF;
  --sl-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, sans-serif;
  --sl-mono: ui-monospace, 'SF Mono', 'Cascadia Code', 'Roboto Mono', monospace;
}
.sl-root {
  background: var(--sl-void);
  color: var(--sl-text);
  font-family: var(--sl-sans);
  border-radius: 14px;
  padding: 22px 24px 28px;
  max-width: 980px;
  margin: 0 auto;
  border: 1px solid var(--sl-border);
}
.sl-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.sl-brand { display: flex; align-items: center; gap: 10px; }
.sl-brand-mark { width: 34px; height: 34px; border-radius: 9px; background: var(--sl-panel-2); display: flex; align-items: center; justify-content: center; border: 1px solid var(--sl-border); }
.sl-brand-name { font-weight: 700; font-size: 15px; letter-spacing: 0.2px; }
.sl-brand-sub { font-size: 10.5px; color: var(--sl-muted); letter-spacing: 0.3px; margin-top: 1px; }

.sl-titlebar { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.sl-strategy-name { background: transparent; border: none; color: var(--sl-text); font-size: 21px; font-weight: 700; outline: none; padding: 2px 0; width: auto; min-width: 60px; }
.sl-legcount { font-size: 11.5px; color: var(--sl-muted); font-family: var(--sl-mono); }

.sl-symbolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.sl-symbol-input { background: var(--sl-panel-2); border: 1px solid var(--sl-border); color: var(--sl-text); font-family: var(--sl-mono); font-weight: 700; font-size: 13px; padding: 8px 12px; border-radius: 8px; width: 84px; text-transform: uppercase; }
.sl-price { display: flex; align-items: baseline; gap: 8px; }
.sl-price-value { font-family: var(--sl-mono); font-size: 15px; font-weight: 700; }
.sl-price-change { font-family: var(--sl-mono); font-size: 11.5px; color: var(--sl-up); }
.sl-loading-tag { font-size: 11px; color: var(--sl-amber); font-family: var(--sl-mono); }

.sl-exp-label { font-size: 10.5px; color: var(--sl-muted); letter-spacing: 0.6px; margin-bottom: 8px; }
.sl-exp-row { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; margin-bottom: 22px; }
.sl-exp-pill { flex: 0 0 auto; background: var(--sl-panel-2); border: 1px solid var(--sl-border); border-radius: 8px; padding: 6px 11px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 1px; color: var(--sl-muted); }
.sl-exp-pill .sl-exp-month { font-size: 9px; letter-spacing: 0.4px; }
.sl-exp-pill .sl-exp-day { font-family: var(--sl-mono); font-size: 13px; font-weight: 700; color: var(--sl-text); }
.sl-exp-pill.active { background: var(--sl-amber); border-color: var(--sl-amber); }
.sl-exp-pill.active .sl-exp-day { color: #1A1300; }
.sl-exp-pill.active .sl-exp-month { color: #4A3200; }

.sl-ruler { margin-bottom: 24px; }
.sl-ruler-label { font-size: 10.5px; color: var(--sl-muted); letter-spacing: 0.6px; margin-bottom: 22px; }
.sl-ruler-track { position: relative; height: 6px; background: var(--sl-panel-2); border-radius: 3px; margin: 0 6px; }
.sl-ruler-line { position: absolute; inset: 0; border-radius: 3px; background: linear-gradient(90deg, #232838, #2C3247); }
.sl-ruler-tick { position: absolute; top: 10px; transform: translateX(-50%); font-family: var(--sl-mono); font-size: 10px; color: var(--sl-muted); }
.sl-ruler-spot { position: absolute; top: -22px; transform: translateX(-50%); text-align: center; }
.sl-ruler-spot-label { font-size: 8.5px; color: var(--sl-amber); letter-spacing: 0.5px; display: block; }
.sl-ruler-spot-arrow { color: var(--sl-amber); font-size: 11px; display: block; margin-top: -2px; }
.sl-ruler-tag { position: absolute; top: -44px; transform: translateX(-50%); font-family: var(--sl-mono); font-size: 10.5px; font-weight: 700; padding: 3px 7px; border-radius: 6px; white-space: nowrap; }
.sl-ruler-tag.tag-sell.tag-put { background: rgba(255,93,93,0.18); color: var(--sl-down); border: 1px solid rgba(255,93,93,0.4); }
.sl-ruler-tag.tag-sell.tag-call { background: rgba(61,220,151,0.18); color: var(--sl-up); border: 1px solid rgba(61,220,151,0.4); }
.sl-ruler-tag.tag-buy.tag-call { background: rgba(91,141,239,0.18); color: var(--sl-blue); border: 1px solid rgba(91,141,239,0.4); }
.sl-ruler-tag.tag-buy.tag-put { background: rgba(91,141,239,0.18); color: var(--sl-blue); border: 1px solid rgba(91,141,239,0.4); }

.sl-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
.sl-metric { background: var(--sl-panel); border: 1px solid var(--sl-border); border-radius: 10px; padding: 12px 14px; }
.sl-metric-label { font-size: 10px; color: var(--sl-muted); letter-spacing: 0.5px; display: flex; align-items: center; gap: 5px; margin-bottom: 6px; }
.sl-metric-icon { font-size: 10px; }
.sl-metric-value { font-family: var(--sl-mono); font-size: 17px; font-weight: 700; }
.sl-metric-value.tone-up { color: var(--sl-up); }
.sl-metric-value.tone-down { color: var(--sl-down); }
.sl-metric-value.tone-flat { color: var(--sl-blue); font-size: 14px; }
.sl-metric-sub { font-size: 10.5px; color: var(--sl-muted); margin-top: 3px; font-family: var(--sl-mono); }

.sl-chart-wrap { background: var(--sl-panel); border: 1px solid var(--sl-border); border-radius: 12px; padding: 14px 6px 4px; margin-bottom: 14px; }
.sl-chart-caption { text-align: center; font-size: 10.5px; color: var(--sl-muted); padding: 6px 0 8px; font-family: var(--sl-mono); }
.sl-tooltip { background: #0D1018; border: 1px solid var(--sl-border); border-radius: 8px; padding: 8px 11px; }
.sl-tooltip-price { font-family: var(--sl-mono); font-size: 11px; color: var(--sl-muted); margin-bottom: 2px; }
.sl-tooltip-pl { font-family: var(--sl-mono); font-size: 13px; font-weight: 700; }
.sl-tooltip-pl.tone-up { color: var(--sl-up); }
.sl-tooltip-pl.tone-down { color: var(--sl-down); }

.sl-table-wrap { background: var(--sl-panel); border: 1px solid var(--sl-border); border-radius: 12px; padding: 14px 10px 4px; margin-bottom: 14px; overflow-x: auto; }
.sl-ptable { display: grid; gap: 2px; min-width: 560px; }
.sl-ptable-cell { font-family: var(--sl-mono); font-size: 11px; text-align: center; padding: 7px 4px; border-radius: 4px; }
.sl-ptable-corner { color: var(--sl-muted); font-size: 10px; }
.sl-ptable-colhead { color: var(--sl-muted); font-size: 10px; letter-spacing: 0.3px; }
.sl-ptable-strike { color: var(--sl-text); font-weight: 700; background: var(--sl-panel-2); }
.sl-ptable-val { font-weight: 600; }
.sl-ptable-spotrow.sl-ptable-strike { outline: 1px solid var(--sl-amber); color: var(--sl-amber); }
.sl-ptable-spotrow.sl-ptable-val { box-shadow: inset 0 0 0 1px rgba(240,168,104,0.5); }

.sl-chain { display: flex; flex-direction: column; gap: 2px; min-width: 480px; }
.sl-chain-row { display: grid; grid-template-columns: 60px 64px 64px 72px 64px 64px 60px; gap: 2px; align-items: center; }
.sl-chain-row > span { font-family: var(--sl-mono); font-size: 11.5px; text-align: center; padding: 6px 4px; border-radius: 4px; }
.sl-chain-head span { font-size: 10px; letter-spacing: 0.6px; color: var(--sl-muted); }
.sl-chain-subhead span { color: var(--sl-muted); font-size: 10px; }
.sl-chain-strike { font-weight: 700; background: var(--sl-panel-2); color: var(--sl-text); }
.sl-chain-delta { color: var(--sl-muted); }
.sl-chain-bid { cursor: pointer; color: var(--sl-down); }
.sl-chain-bid:hover { background: rgba(255,93,93,0.15); }
.sl-chain-ask { cursor: pointer; color: var(--sl-up); }
.sl-chain-ask:hover { background: rgba(61,220,151,0.15); }
.sl-chain-disabled { cursor: default; color: var(--sl-muted); opacity: 0.5; }
.sl-chain-disabled:hover { background: none; }
.sl-chain-atm .sl-chain-strike { outline: 1px solid var(--sl-amber); color: var(--sl-amber); }
.sl-chain-empty { color: var(--sl-muted); font-size: 12.5px; padding: 20px 0; text-align: center; }

.sl-tabs { display: flex; gap: 4px; margin-bottom: 20px; border: 1px solid var(--sl-border); border-radius: 10px; padding: 4px; overflow-x: auto; }
.sl-tab { flex: 1 0 auto; background: none; border: none; color: var(--sl-muted); font-size: 12px; font-weight: 600; padding: 8px 12px; border-radius: 7px; cursor: pointer; white-space: nowrap; font-family: var(--sl-sans); }
.sl-tab.active { background: var(--sl-amber); color: #1A1300; }
.sl-tab-disabled { opacity: 0.35; cursor: not-allowed; }

.sl-sliderrow { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.sl-slider-label { font-size: 11px; color: var(--sl-muted); font-family: var(--sl-mono); width: 130px; flex-shrink: 0; }
.sl-slider { flex: 1; accent-color: var(--sl-amber); }

.sl-legs { border-top: 1px solid var(--sl-border); padding-top: 16px; }
.sl-legs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.sl-legs-header span { font-size: 10.5px; color: var(--sl-muted); letter-spacing: 0.6px; }
.sl-add-btn { background: none; border: 1px solid var(--sl-border); color: var(--sl-amber); font-size: 11.5px; padding: 5px 10px; border-radius: 6px; cursor: pointer; font-family: var(--sl-mono); }
.sl-add-btn:hover { border-color: var(--sl-amber); }
.sl-legs-table { display: flex; flex-direction: column; gap: 6px; }
.sl-legs-row { display: grid; grid-template-columns: 74px 56px 84px 1fr 1fr 28px; gap: 8px; align-items: center; }
.sl-legs-row-head span { font-size: 10px; color: var(--sl-muted); letter-spacing: 0.4px; }
.sl-cell { background: var(--sl-panel-2); border: 1px solid var(--sl-border); color: var(--sl-text); font-family: var(--sl-mono); font-size: 12.5px; padding: 7px 8px; border-radius: 7px; width: 100%; box-sizing: border-box; }
.sl-side-sell { color: var(--sl-down); font-weight: 700; }
.sl-side-buy { color: var(--sl-up); font-weight: 700; }
.sl-remove-btn { background: none; border: none; color: var(--sl-muted); font-size: 18px; cursor: pointer; line-height: 1; }
.sl-remove-btn:hover { color: var(--sl-down); }
.sl-legs-empty { color: var(--sl-muted); font-size: 12.5px; padding: 14px 0; }

.sl-footer { text-align: center; font-size: 10.5px; color: var(--sl-muted); margin-top: 22px; font-family: var(--sl-mono); }

@media (max-width: 640px) {
  .sl-metrics { grid-template-columns: repeat(2, 1fr); }
  .sl-legs-row { grid-template-columns: 62px 46px 68px 1fr 1fr 24px; }
}
`;
