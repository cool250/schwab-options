import { useState, useEffect } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  Tooltip,
} from "recharts";
import { getPriceHistory } from "../api/client";
import { symbolStore } from "../utils/symbolStore";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);

const formatDateLabel = (dateStr) =>
  new Date(`${dateStr}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

export default function Charts() {
  // symbolStore is shared with Analyze (StrikeLab, and always has a value,
  // its own default included) — switching symbol here carries over there,
  // and vice versa, instead of each page drifting independently.
  const [symbol, setSymbol] = useState(symbolStore.symbol);
  const [symbolInput, setSymbolInput] = useState(symbolStore.symbol);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    symbolStore.symbol = symbol;
    if (!symbol) {
      setHistory(null);
      setError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const result = await getPriceHistory(symbol, 30);
        if (cancelled) return;
        if (result?.candles?.length) {
          setHistory(result);
          setError(null);
        } else {
          setHistory(null);
          setError(result?.message || "No price history available for this symbol.");
        }
      } catch (e) {
        console.error("Failed to load price history:", e);
        if (!cancelled) {
          setHistory(null);
          setError(e.message || "Failed to load price history.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const submitSymbol = (e) => {
    e.preventDefault();
    const s = symbolInput.trim().toUpperCase();
    if (s) setSymbol(s);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">Charts</h2>
      </div>

      <div className="card">
        <div className="form-group form-group--sm">
          <label>Symbol</label>
          <form onSubmit={submitSymbol}>
            <input
              className="input"
              placeholder="e.g. AAPL"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            />
          </form>
        </div>
      </div>

      <div className="card">
        <PriceHistoryChart history={history} loading={loading} error={symbol ? error : null} noSymbol={!symbol} />
      </div>
    </div>
  );
}

/** One candle's wick + body, drawn as a custom Bar `shape`. Recharts sizes
 *  the Bar itself (x/y/width/height) from the `range` dataKey — [low, high]
 *  mapped through the y-axis scale, so y/y+height already land exactly on
 *  the pixel positions for this candle's high/low. open/close aren't part
 *  of that range, so their pixel positions are interpolated linearly
 *  between the same two points (valid since the y-axis is linear, which is
 *  the only kind Recharts' YAxis renders here). */
function Candle({ x, y, width, height, payload }) {
  const { open, close, high, low } = payload;
  if (![open, close, high, low].every(isNum)) return null;

  const isUp = close >= open;
  const color = isUp ? "var(--success)" : "var(--error)";
  const span = high - low || 1;
  const yFor = (price) => y + ((high - price) / span) * height;
  const bodyTop = Math.min(yFor(open), yFor(close));
  const bodyHeight = Math.max(Math.abs(yFor(open) - yFor(close)), 1);
  const bodyWidth = Math.max(width * 0.6, 2);
  const wickX = x + width / 2;

  return (
    <g>
      <line x1={wickX} x2={wickX} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x + (width - bodyWidth) / 2} y={bodyTop} width={bodyWidth} height={bodyHeight} fill={color} />
    </g>
  );
}

/** Last-30-days daily candlesticks with swing support/resistance levels
 *  (see service/market.py's _swing_levels) drawn as horizontal reference
 *  lines. Backed by Schwab regardless of BROKER_PROVIDER — Tastytrade has
 *  no REST daily-bar endpoint — so this may come back empty for a futures
 *  root like "/NQ" even when the option chain elsewhere is working fine. */
function PriceHistoryChart({ history, loading, error, noSymbol }) {
  if (noSymbol) {
    return <div className="chain-empty">Enter a symbol to get started</div>;
  }
  if (error) {
    return <div className="chain-empty">{error}</div>;
  }
  if (!history) {
    return <div className="chain-empty">{loading ? "Loading price history…" : "No price history available."}</div>;
  }

  const chartData = history.candles.map((c) => ({ ...c, range: [c.low, c.high] }));

  return (
    <>
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDateLabel}
            stroke="var(--text-faint)"
            tick={{ fontSize: 12 }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            domain={["auto", "auto"]}
            tickFormatter={(v) => `$${Math.round(v)}`}
            stroke="var(--text-faint)"
            tick={{ fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={56}
          />
          <Tooltip content={<PriceHistoryTooltip />} />
          {history.resistance.map((lvl, i) => (
            <ReferenceLine
              key={`r${i}`}
              y={lvl}
              stroke="var(--error)"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              label={{ value: `R $${lvl.toFixed(2)}`, position: "insideTopRight", fill: "var(--error)", fontSize: 11 }}
            />
          ))}
          {history.support.map((lvl, i) => (
            <ReferenceLine
              key={`s${i}`}
              y={lvl}
              stroke="var(--success)"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              label={{ value: `S $${lvl.toFixed(2)}`, position: "insideBottomRight", fill: "var(--success)", fontSize: 11 }}
            />
          ))}
          <Bar dataKey="range" shape={Candle} isAnimationActive={true} animationDuration={700} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="chart-caption">Last 30 days · daily candles with swing support/resistance</p>
    </>
  );
}

function PriceHistoryTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const { open, high, low, close } = payload[0].payload;
  const isUp = close >= open;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-price">{formatDateLabel(label)}</div>
      <div className={`chart-tooltip-pl ${isUp ? "positive" : "negative"}`}>
        O {open.toFixed(2)} · H {high.toFixed(2)} · L {low.toFixed(2)} · C {close.toFixed(2)}
      </div>
    </div>
  );
}
