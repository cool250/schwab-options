import React, { useState, useMemo, useCallback, useEffect } from "react";
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
import { getOptionChain, getExpirationList } from "../api/client";

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
  // Net-short puts are worst when the stock goes to zero, which may fall outside [lo, hi].
  const zeroPL = totalPL(legs, 0);
  if (zeroPL < minP) minP = zeroPL;

  // A net-short call position (not capped by a higher-strike long call) loses without
  // bound as price rises — no finite sample range can capture that, so flag it directly.
  const callSlope = legs.reduce(
    (sum, leg) =>
      leg.type === "CALL" ? sum + (leg.side === "BUY" ? 1 : -1) * leg.qty * MULTIPLIER : sum,
    0
  );
  if (callSlope < 0) minP = -Infinity;

  return { maxProfit: maxP, maxLoss: minP };
}

const DEFAULT_SYMBOL = "SPY";
const DEFAULT_SPOT = 0;

/** Splits a "YYYY-MM-DD" date into the { month, day } shown on an expiration pill. */
function expPillParts(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`);
  return { month: d.toLocaleDateString("en-US", { month: "short" }), day: String(d.getDate()) };
}

/* ============================================================================
   UI HELPERS
============================================================================ */

const fmtMoney = (n) => {
  const abs = Math.abs(n);
  const s = abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "-" : ""}$${s}`;
};

const formatExpLabel = (dateStr) =>
  new Date(`${dateStr}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/* ============================================================================
   MAIN PAGE
============================================================================ */

export default function StrikeLab() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [symbolInput, setSymbolInput] = useState(DEFAULT_SYMBOL);
  const [spot, setSpot] = useState(DEFAULT_SPOT);
  const [expIndex, setExpIndex] = useState(0);
  const [legs, setLegs] = useState([]);
  const [rangePct, setRangePct] = useState(3.6);
  const [ivPct, setIvPct] = useState(10.9);
  const [chain, setChain] = useState(null);
  const [loadingChain, setLoadingChain] = useState(false);
  const [view, setView] = useState("chain"); // 'chain' | 'table' | 'graph'

  const [expirations, setExpirations] = useState([]); // [{date, dte}] — real listed expirations, incl. daily where offered
  const dte = expirations[expIndex]?.dte;
  // The pill above only controls which chain you're browsing to add new legs —
  // an already-built position keeps the expiration it was actually added at,
  // so time decay (Table/Graph) must track the legs' own dte, not the pill.
  // Use the most recently added leg: if legs span multiple expirations, the
  // latest one reflects what you're currently building toward.
  const positionDte = legs.length > 0 ? legs[legs.length - 1].dte : dte;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await getExpirationList(symbol);
        if (!cancelled) setExpirations(result || []);
      } catch (e) {
        if (!cancelled) setExpirations([]);
      }
      if (!cancelled) setExpIndex(0);
    })();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const loadChain = useCallback(async () => {
    if (dte == null) return;
    setLoadingChain(true);
    try {
      const result = await getOptionChain(symbol, dte);
      if (result && result.chain) {
        setChain(result);
        setSpot(result.spot);
        // Some brokers (e.g. Tastytrade) don't expose chain-level IV — keep
        // whatever IV is already set rather than zeroing it out.
        if (result.iv != null) setIvPct(result.iv * 100);
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
    if (dte != null) loadChain();
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
    setLegs((prev) => {
      // Idempotent: a bid/ask click for a strike/side already in the position is a
      // no-op rather than a duplicate leg — otherwise a double-click on an already
      // selected cell would race with the row's double-click-to-remove handler
      // (two "click" events fire before "dblclick" does).
      if (prev.some((l) => l.strike === strike && l.type === type && l.side === side)) {
        return prev;
      }
      return [...prev, { id: `l${Date.now()}`, side, qty: 1, type, strike, premium: +premium.toFixed(2), dte }];
    });
  };

  const submitSymbol = (e) => {
    e.preventDefault();
    const s = symbolInput.trim().toUpperCase();
    if (s && s !== symbol) {
      setSymbol(s);
      setLegs([]); // strikes belong to the old ticker's chain — don't carry them over
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">StrikeLab</h2>
      </div>

      {/* ---------------- Symbol / strategy / expirations / ruler ---------------- */}
      <div className="card">
        <div className="symbol-exp-row">
          <div className="form-group form-group--sm">
            <label>Symbol</label>
            <form onSubmit={submitSymbol}>
              <input
                className="input"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
              />
            </form>
            <span className="price-badge ok">
              Current price: ${spot.toFixed(2)}
              {loadingChain ? " · syncing chain…" : ""}
            </span>
          </div>

          <div className="exp-group">
            <span className="metric-label">Expiration{dte != null ? ` · ${dte}d` : ""}</span>
            <div className="exp-pills">
              {expirations.length === 0 && <span className="text-muted">Loading expirations…</span>}
              {expirations.map((e, i) => {
                const { month, day } = expPillParts(e.date);
                return (
                  <button
                    key={e.date}
                    className={`exp-pill ${i === expIndex ? "active" : ""}`}
                    onClick={() => setExpIndex(i)}
                  >
                    <span className="exp-pill-month">{month}</span>
                    <span className="exp-pill-day">{day}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* ---------------- Legs editor ---------------- */}
      <div className="card">
        <div className="section-header" style={{ justifyContent: "space-between" }}>
          <h3 className="section-title">Strikes</h3>
          <button className="btn btn-secondary" onClick={addLeg}>
            + Add Leg
          </button>
        </div>
        <StrikeRuler legs={legs} spot={spot} lo={lo} hi={hi} />
        <span className="summary-line">
          {legs.length} leg{legs.length !== 1 ? "s" : ""}
        </span>
        <div className="legs-table">
          <div className="leg-row leg-row-head">
            <span>Side</span>
            <span>Qty</span>
            <span>Type</span>
            <span>Strike</span>
            <span>Premium</span>
            <span></span>
          </div>
          {legs.map((leg) => (
            <div className="leg-row" key={leg.id}>
              <select
                className={`leg-cell leg-side-${leg.side.toLowerCase()}`}
                value={leg.side}
                onChange={(e) => updateLeg(leg.id, { side: e.target.value })}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
              <input
                className="leg-cell"
                type="number"
                min="1"
                value={leg.qty}
                onChange={(e) => updateLeg(leg.id, { qty: Math.max(1, +e.target.value) })}
              />
              <select
                className="leg-cell"
                value={leg.type}
                onChange={(e) => updateLeg(leg.id, { type: e.target.value })}
              >
                <option value="CALL">CALL</option>
                <option value="PUT">PUT</option>
              </select>
              <input
                className="leg-cell"
                type="number"
                step="0.5"
                value={leg.strike}
                onChange={(e) => updateLeg(leg.id, { strike: +e.target.value })}
              />
              <input
                className="leg-cell"
                type="number"
                step="0.01"
                value={leg.premium}
                onChange={(e) => updateLeg(leg.id, { premium: Math.max(0, +e.target.value) })}
              />
              <button className="leg-remove" onClick={() => removeLeg(leg.id)} title="Remove leg">
                ×
              </button>
            </div>
          ))}
          {legs.length === 0 && (
            <div className="legs-empty">No legs yet — add one to start building a payoff.</div>
          )}
        </div>
      </div>

      {/* ---------------- Metrics ---------------- */}
      <div className="card">
        <div className="metrics-row">
          <div className="metric">
            <span className="metric-label">Net Credit</span>
            <span className={`metric-value ${credit >= 0 ? "positive" : "negative"}`}>
              {fmtMoney(Math.abs(credit))}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Max Loss</span>
            <span className="metric-value negative">
              {maxLoss === -Infinity ? "Unlimited" : fmtMoney(Math.abs(maxLoss))}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Max Profit</span>
            <span className="metric-value positive">{fmtMoney(Math.abs(maxProfit))}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Breakeven</span>
            <span className="metric-value highlight">
              {breakevens.length
                ? breakevens.map((b) => `$${b.toFixed(2)}`).join(" / ")
                : "None in range"}
            </span>
            {breakevens.length > 0 && (
              <span className="text-muted">
                {(((breakevens[0] - spot) / spot) * 100).toFixed(1)}% from spot
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ---------------- Chain / Table / Graph ---------------- */}
      <div className="card">
        <div className="button-row">
          {[
            { id: "chain", label: "Chain" },
            { id: "table", label: "Table" },
            { id: "graph", label: "Graph" },
          ].map((t) => (
            <button
              key={t.id}
              className={`btn ${view === t.id ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setView(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {positionDte == null ? (
          <div className="chain-empty">Loading expirations…</div>
        ) : view === "graph" ? (
          <>
            <ResponsiveContainer width="100%" height={340}>
              <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                <defs>
                  <linearGradient id="payoffPos" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--success)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="var(--success)" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="payoffNeg" x1="0" y1="1" x2="0" y2="0">
                    <stop offset="0%" stopColor="var(--error)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="var(--error)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="price"
                  type="number"
                  domain={[lo, hi]}
                  tickFormatter={(v) => `$${Math.round(v)}`}
                  stroke="var(--text-faint)"
                  tick={{ fontSize: 12 }}
                  tickLine={false}
                />
                <YAxis
                  tickFormatter={(v) => (v === 0 ? "$0" : `${v > 0 ? "+" : ""}${v}`)}
                  stroke="var(--text-faint)"
                  tick={{ fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                />
                <Tooltip content={<PayoffTooltip />} />
                <ReferenceLine y={0} stroke="var(--border-strong)" strokeWidth={1.5} />
                <ReferenceLine x={spot} stroke="var(--primary)" strokeDasharray="4 4" strokeWidth={1.5} />
                {breakevens.map((b, i) => (
                  <ReferenceLine key={i} x={b} stroke="#7c3aed" strokeDasharray="2 2" strokeWidth={1} />
                ))}
                <Area
                  dataKey="pos"
                  stroke="var(--success)"
                  strokeWidth={2}
                  fill="url(#payoffPos)"
                  isAnimationActive={true}
                  animationDuration={700}
                  dot={false}
                />
                <Area
                  dataKey="neg"
                  stroke="var(--error)"
                  strokeWidth={2}
                  fill="url(#payoffNeg)"
                  isAnimationActive={true}
                  animationDuration={700}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
            <p className="chart-caption">Payoff shown at expiration · {positionDte} days out</p>
          </>
        ) : view === "table" ? (
          <PLTable
            legs={legs}
            spot={spot}
            lo={lo}
            hi={hi}
            dte={positionDte}
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
            onRemoveLeg={removeLeg}
            legs={legs}
          />
        )}
      </div>

      {/* ---------------- Range / IV sliders ---------------- */}
      <div className="card">
        <div className="slider-row">
          <span className="slider-label">Range ±{rangePct.toFixed(1)}%</span>
          <input
            type="range"
            min="0.5"
            max="15"
            step="0.1"
            value={rangePct}
            onChange={(e) => setRangePct(+e.target.value)}
            className="range-slider"
          />
        </div>
        <div className="slider-row">
          <span className="slider-label">Implied Vol {ivPct.toFixed(1)}%</span>
          <input
            type="range"
            min="2"
            max="60"
            step="0.1"
            value={ivPct}
            onChange={(e) => setIvPct(+e.target.value)}
            className="range-slider"
          />
        </div>
      </div>

      <p className="text-muted" style={{ textAlign: "center" }}>
        Simplified intrinsic-value model at expiration · not investment advice
      </p>
    </div>
  );
}

/* ============================================================================
   Strike ruler — horizontal number line with leg markers
============================================================================ */
function StrikeRuler({ legs, spot, lo, hi }) {
  const width = 100;
  const strikes = legs.map((l) => l.strike);
  const effLo = Math.min(lo, ...strikes);
  const effHi = Math.max(hi, ...strikes);
  const pct = (price) => ((price - effLo) / (effHi - effLo)) * width;
  const ticks = [];
  const tickStep = (effHi - effLo) / 8;
  for (let i = 0; i <= 8; i++) ticks.push(effLo + i * tickStep);

  return (
    <div className="strike-ruler">
      <span className="metric-label">Strikes</span>
      <div className="ruler-track">
        <div className="ruler-line" />
        {ticks.map((t, i) => (
          <div key={i} className="ruler-tick" style={{ left: `${pct(t)}%` }}>
            <span>${Math.round(t)}</span>
          </div>
        ))}
        <div className="ruler-spot" style={{ left: `${pct(spot)}%` }}>
          <span className="ruler-spot-label">SPOT</span>
          <span className="ruler-spot-arrow">▾</span>
        </div>
        {legs.map((leg) => (
          <div
            key={leg.id}
            className={`ruler-tag ${leg.side === "SELL" ? "tag-sell tag-below" : "tag-buy tag-above"} tag-${leg.type.toLowerCase()}`}
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
    const alpha = 0.08 + t * 0.55;
    return { background: `rgba(5, 150, 105, ${alpha})`, color: t > 0.5 ? "#ffffff" : "#065f32" };
  }
  const t = maxLoss < 0 ? Math.min(1, value / maxLoss) : 0;
  const alpha = 0.08 + t * 0.55;
  return { background: `rgba(220, 38, 38, ${alpha})`, color: t > 0.5 ? "#ffffff" : "#7f1d1d" };
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

  // maxLoss can be -Infinity for a genuinely unbounded strategy — fall back to the
  // grid's own worst theoretical value so the heatmap coloring stays meaningful.
  const colorMaxLoss = Number.isFinite(maxLoss)
    ? maxLoss
    : grid.reduce((min, row) => Math.min(min, ...row.values), 0);

  return (
    <>
      <div className="table-scroll">
        <div className="pl-heatmap" style={{ gridTemplateColumns: `70px repeat(${dteCols.length}, 1fr)` }}>
          <div className="pl-cell pl-corner">Strike</div>
          {dteCols.map((d, i) => (
            <div key={i} className="pl-cell pl-colhead">
              {dteToLabel(d, dte)}
            </div>
          ))}
          {grid.map((row, ri) => (
            <React.Fragment key={ri}>
              <div className={`pl-cell pl-strike ${ri === spotRowIdx ? "pl-spotrow" : ""}`}>
                ${row.price.toFixed(0)}
              </div>
              {row.values.map((v, ci) => {
                const style = cellColor(v, maxProfit, colorMaxLoss);
                return (
                  <div
                    key={ci}
                    className={`pl-cell pl-value ${ri === spotRowIdx ? "pl-spotrow" : ""}`}
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
      </div>
      <p className="chart-caption">
        Theoretical value pre-expiration (IV {(iv * 100).toFixed(1)}%) · intrinsic value at "Exp"
      </p>
    </>
  );
}

/* ============================================================================
   Option chain view — standard Calls | Strike | Puts table around ATM
============================================================================ */
const DEFAULT_CHAIN_RADIUS = 10; // strikes shown on each side of ATM

function OptionChainTable({ chain, spot, loading, onAddLeg, onRemoveLeg, legs }) {
  const [radius, setRadius] = useState(DEFAULT_CHAIN_RADIUS);
  const rows = chain?.chain;

  if (!rows || rows.length === 0) {
    return (
      <div className="chain-empty">
        {loading ? "Loading option chain…" : "No option chain available for this symbol/expiration."}
      </div>
    );
  }

  const sorted = [...rows].sort((a, b) => a.strikePrice - b.strikePrice);
  const atmIdx = sorted.reduce(
    (best, row, i) =>
      Math.abs(row.strikePrice - spot) < Math.abs(sorted[best].strikePrice - spot) ? i : best,
    0
  );
  const start = Math.max(0, atmIdx - radius);
  const end = Math.min(sorted.length, atmIdx + radius + 1);
  const visible = sorted.slice(start, end);
  const atmStrike = sorted[atmIdx].strikePrice;

  return (
    <>
      <div className="slider-row">
        {chain?.expirationDate && (
          <span className="chain-week-badge">
            {formatExpLabel(chain.expirationDate)} · {chain.dte}d
          </span>
        )}
        <span className="slider-label" style={{ marginLeft: "auto" }}>Strikes each side</span>
        <input
          className="input"
          type="number"
          min="1"
          max={Math.ceil(sorted.length / 2)}
          value={radius}
          onChange={(e) => setRadius(Math.max(1, +e.target.value || 1))}
          style={{ maxWidth: 70 }}
        />
      </div>
      <div className="table-scroll">
        <div className="chain-table">
          <div className="chain-row chain-head">
            <span style={{ gridColumn: "1 / 2" }} />
            <span className="chain-side-label" style={{ gridColumn: "2 / 5" }}>CALLS</span>
            <span style={{ gridColumn: "5 / 6" }} />
            <span className="chain-side-label" style={{ gridColumn: "6 / 9" }}>PUTS</span>
            <span style={{ gridColumn: "9 / 10" }} />
          </div>
          <div className="chain-row chain-subhead">
            <span></span>
            <span>Delta</span>
            <span>Bid</span>
            <span>Ask</span>
            <span>Strike</span>
            <span>Bid</span>
            <span>Ask</span>
            <span>Delta</span>
            <span></span>
          </div>
          {visible.map((row) => {
            const isAtm = row.strikePrice === atmStrike;
            const callLeg = legs.find((l) => l.strike === row.strikePrice && l.type === "CALL");
            const putLeg = legs.find((l) => l.strike === row.strikePrice && l.type === "PUT");
            const isSelected = Boolean(callLeg || putLeg);
            const deselect = () => {
              if (callLeg) onRemoveLeg(callLeg.id);
              if (putLeg) onRemoveLeg(putLeg.id);
            };
            return (
              <div
                key={row.strikePrice}
                className={`chain-row ${isAtm ? "chain-atm" : ""} ${isSelected ? "chain-row-selected" : ""}`}
                onDoubleClick={isSelected ? deselect : undefined}
                title={isSelected ? "Double-click to remove this strike" : undefined}
              >
                <span className="chain-leg-col">
                  {callLeg && (
                    <span className={`chain-leg-badge ${callLeg.side === "SELL" ? "tag-sell" : "tag-buy"}`}>
                      {callLeg.side === "SELL" ? "STO" : "BTO"}
                    </span>
                  )}
                </span>
                <span className="chain-delta">{row.call?.delta != null ? row.call.delta.toFixed(2) : "—"}</span>
                <span
                  className={`chain-bid ${row.call?.bid != null ? "" : "chain-disabled"}`}
                  onClick={() => row.call?.bid != null && onAddLeg("CALL", "SELL", row.strikePrice, row.call.bid)}
                  title={row.call?.bid != null ? "Sell a call at bid" : undefined}
                >
                  {row.call?.bid != null ? row.call.bid.toFixed(2) : "—"}
                </span>
                <span
                  className={`chain-ask ${row.call?.ask != null ? "" : "chain-disabled"}`}
                  onClick={() => row.call?.ask != null && onAddLeg("CALL", "BUY", row.strikePrice, row.call.ask)}
                  title={row.call?.ask != null ? "Buy a call at ask" : undefined}
                >
                  {row.call?.ask != null ? row.call.ask.toFixed(2) : "—"}
                </span>
                <span className="chain-strike">{row.strikePrice}</span>
                <span
                  className={`chain-bid ${row.put?.bid != null ? "" : "chain-disabled"}`}
                  onClick={() => row.put?.bid != null && onAddLeg("PUT", "SELL", row.strikePrice, row.put.bid)}
                  title={row.put?.bid != null ? "Sell a put at bid" : undefined}
                >
                  {row.put?.bid != null ? row.put.bid.toFixed(2) : "—"}
                </span>
                <span
                  className={`chain-ask ${row.put?.ask != null ? "" : "chain-disabled"}`}
                  onClick={() => row.put?.ask != null && onAddLeg("PUT", "BUY", row.strikePrice, row.put.ask)}
                  title={row.put?.ask != null ? "Buy a put at ask" : undefined}
                >
                  {row.put?.ask != null ? row.put.ask.toFixed(2) : "—"}
                </span>
                <span className="chain-delta">{row.put?.delta != null ? row.put.delta.toFixed(2) : "—"}</span>
                <span className="chain-leg-col">
                  {putLeg && (
                    <span className={`chain-leg-badge ${putLeg.side === "SELL" ? "tag-sell" : "tag-buy"}`}>
                      {putLeg.side === "SELL" ? "STO" : "BTO"}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <p className="chart-caption">
        Click a bid to sell, an ask to buy · {visible.length} of {sorted.length} strikes shown
      </p>
    </>
  );
}

function PayoffTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const pl = payload[0].payload.pl;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-price">${(+label).toFixed(2)}</div>
      <div className={`chart-tooltip-pl ${pl >= 0 ? "positive" : "negative"}`}>
        {pl >= 0 ? "+" : ""}
        {fmtMoney(pl)}
      </div>
    </div>
  );
}
