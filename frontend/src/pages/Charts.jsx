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
import { getPriceHistory, getOptionChain, friendlyErrorMessage } from "../api/client";
import { symbolStore } from "../utils/symbolStore";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);

// Every button on the Charts page's timeframe row, in display order — see
// service/market.py's _RANGE_PARAMS for what each one actually fetches
// (bar size and how far back).
const RANGES = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"];

// Candle timestamps are a full ISO datetime now (see service/market.py),
// not just a date, since 1D/5D are intraday bars — but how much of that to
// actually show depends on the selected range: a time-of-day for a single
// day, a coarser month/day for the middle ranges, and just month/year once
// each candle is a week or a month wide (5Y/MAX) rather than a day.
const formatDateLabel = (dateStr, range) => {
  const d = new Date(dateStr);
  if (range === "1D") return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  if (range === "5D") return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" });
  if (range === "5Y" || range === "MAX") return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

// Matches _RANGE_PARAMS' bar size on the backend — shown in the chart's
// caption so "swing support/resistance" always reads next to what it was
// actually computed from.
const RANGE_CAPTION = {
  "1D": "Today · 5-min candles",
  "5D": "Last 5 days · 30-min candles",
  "1M": "Last month · daily candles",
  "6M": "Last 6 months · daily candles",
  YTD: "Year to date · daily candles",
  "1Y": "Last year · daily candles",
  "5Y": "Last 5 years · weekly candles",
  MAX: "Full history · monthly candles",
};

export default function Charts() {
  // symbolStore is shared with Analyze (StrikeLab, and always has a value,
  // its own default included) — switching symbol here carries over there,
  // and vice versa, instead of each page drifting independently.
  const [symbol, setSymbol] = useState(symbolStore.symbol);
  const [symbolInput, setSymbolInput] = useState(symbolStore.symbol);
  const [range, setRange] = useState("1M");
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
        const result = await getPriceHistory(symbol, range);
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
          setError(friendlyErrorMessage(e, e.message || "Failed to load price history."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  const submitSymbol = (e) => {
    e.preventDefault();
    const s = symbolInput.trim().toUpperCase();
    if (s) setSymbol(s);
  };

  return (
    <div className="page">
      <div className="card">
        <div className="form-group form-group--sm">
          <h3 className="section-title">Symbol</h3>
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
        {symbol && (
          <div className="range-row">
            <div className="range-pills">
              {RANGES.map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`range-pill ${r === range ? "active" : ""}`}
                  onClick={() => setRange(r)}
                >
                  {r}
                </button>
              ))}
            </div>
            <ChangeBadge history={history} />
          </div>
        )}
        <PriceHistoryChart history={history} loading={loading} error={symbol ? error : null} noSymbol={!symbol} />
      </div>

      <OptionsSnapshot symbol={symbol} />
    </div>
  );
}

/** % change from the first candle's open to the last candle's close, over
 *  whichever range is currently selected — the colored badge next to the
 *  timeframe buttons. */
function ChangeBadge({ history }) {
  const candles = history?.candles;
  if (!candles || candles.length < 2) return null;
  const first = candles[0];
  const last = candles[candles.length - 1];
  if (!isNum(first.open) || first.open === 0 || !isNum(last.close)) return null;
  const pct = ((last.close - first.open) / first.open) * 100;
  const isUp = pct >= 0;
  return (
    <span className={`chart-tooltip-pl ${isUp ? "positive" : "negative"} range-change-badge`}>
      {isUp ? "+" : ""}
      {pct.toFixed(2)}%
    </span>
  );
}

/** Live options-market snapshot for `symbol`'s nearest expiration: ATM
 *  implied volatility and the put/call volume ratio, each as a gauge, plus
 *  the raw call/put/total volume it's built from.
 *
 *  Deliberately narrower than a typical "options overview" dashboard (no
 *  IV Rank/Percentile, no 52-week IV high/low, no aggregate-across-every-
 *  expiration figures) — those need a year+ of stored IV history this app
 *  doesn't collect, or fundamentals data neither Schwab nor Tastytrade
 *  expose the way they're used here. Everything shown is derived live from
 *  one expiration's chain (see getOptionChain), the same per-contract iv/
 *  volume/openInterest fields StrikeLab's chain table already surfaces. */
function OptionsSnapshot({ symbol }) {
  const [chain, setChain] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) {
      setChain(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    // dte=7 isn't a literal week out — the backend resolves it to whichever
    // real expiration is closest (see service/market.py), same default the
    // REST chain endpoint itself uses.
    getOptionChain(symbol, 7)
      .then((data) => {
        if (cancelled) return;
        if (data?.chain?.length) {
          setChain(data);
          setError(null);
        } else {
          setChain(null);
          setError(data?.message || "No option chain available for this symbol.");
        }
      })
      .catch((e) => {
        console.error("Failed to load option chain:", e);
        if (!cancelled) {
          setChain(null);
          setError(friendlyErrorMessage(e, e.message || "Failed to load options data."));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (!symbol) return null;

  return (
    <div className="card">
      <h3 className="section-title">Options Snapshot</h3>
      {loading ? (
        <div className="chain-empty">Loading options snapshot…</div>
      ) : error ? (
        <div className="chain-empty">{error}</div>
      ) : chain ? (
        <OptionsSnapshotBody chain={chain} />
      ) : (
        <div className="chain-empty">No option chain available for this symbol.</div>
      )}
    </div>
  );
}

function OptionsSnapshotBody({ chain }) {
  const rows = chain.chain;

  let putVolume = 0;
  let callVolume = 0;
  for (const row of rows) {
    if (isNum(row.call?.volume)) callVolume += row.call.volume;
    if (isNum(row.put?.volume)) putVolume += row.put.volume;
  }
  const totalVolume = putVolume + callVolume;
  const putCallRatio = callVolume > 0 ? putVolume / callVolume : null;

  // ATM = the strike closest to spot; average of its call/put IV, same
  // convention SchwabOptionChainProvider._normalize_chain already uses for
  // this chain's own chain-level "iv" field (see service/option_chain_providers.py).
  const atmRow = rows.reduce((a, b) =>
    Math.abs(b.strikePrice - chain.spot) < Math.abs(a.strikePrice - chain.spot) ? b : a
  );
  const atmIvValues = [atmRow.call?.iv, atmRow.put?.iv].filter(isNum);
  const atmIv = atmIvValues.length ? atmIvValues.reduce((s, v) => s + v, 0) / atmIvValues.length : null;

  const sentiment =
    putCallRatio == null ? null : putCallRatio < 0.7 ? "Bullish" : putCallRatio > 1.3 ? "Bearish" : "Neutral";
  const sentimentClass = sentiment === "Bullish" ? "positive" : sentiment === "Bearish" ? "negative" : "";

  return (
    <>
      <p className="summary-line">
        {formatDateLabel(chain.expirationDate)} · {chain.dte}d to expiration
      </p>
      <div className="gauge-row">
        <Gauge
          label="Implied Volatility (ATM)"
          value={atmIv != null ? atmIv * 100 : null}
          min={0}
          max={150}
          format={(v) => `${v.toFixed(1)}%`}
          zones={[
            { to: 30, color: "var(--success)" },
            { to: 70, color: "var(--warning)" },
            { to: 150, color: "var(--error)" },
          ]}
        />
        <Gauge
          label="Put/Call Volume Ratio"
          value={putCallRatio}
          min={0}
          max={2}
          format={(v) => v.toFixed(2)}
          zones={[
            { to: 0.7, color: "var(--success)" },
            { to: 1.3, color: "var(--warning)" },
            { to: 2, color: "var(--error)" },
          ]}
          footer={sentiment && <span className={`chart-tooltip-pl ${sentimentClass}`}>{sentiment}</span>}
        />
      </div>
      <div className="metrics-row">
        <div className="metric">
          <span className="metric-label">Call Volume</span>
          <span className="metric-value">{callVolume.toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Put Volume</span>
          <span className="metric-value">{putVolume.toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Total Volume</span>
          <span className="metric-value highlight">{totalVolume.toLocaleString()}</span>
        </div>
      </div>
      <p className="chart-caption">
        Live Tastytrade data for the {formatDateLabel(chain.expirationDate)} expiration only — not aggregated
        across every expiration.
      </p>
    </>
  );
}

/** A semicircular meter: colored severity zones (see `zones`, each a value
 *  boundary + the color of the band ending there) with a needle pointing at
 *  `value`. `null`/missing value renders a neutral gray needle-less dial
 *  rather than guessing a position. */
function Gauge({ label, value, min, max, format, zones, footer }) {
  const cx = 100;
  const cy = 95;
  const r = 78;
  const strokeWidth = 16;

  const fractionOf = (v) => Math.min(1, Math.max(0, (v - min) / (max - min)));
  // 180deg (left, min) sweeping over the top to 0deg (right, max) — standard
  // math angle convention (0deg = +x axis, increasing counterclockwise).
  const angleOf = (v) => 180 - fractionOf(v) * 180;
  const pointAt = (angleDeg, radius) => {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: cx + radius * Math.cos(rad), y: cy - radius * Math.sin(rad) };
  };
  const arcPath = (fromV, toV) => {
    const a1 = angleOf(fromV);
    const a2 = angleOf(toV);
    const p1 = pointAt(a1, r);
    const p2 = pointAt(a2, r);
    return `M ${p1.x} ${p1.y} A ${r} ${r} 0 0 1 ${p2.x} ${p2.y}`;
  };

  let prev = min;
  const bands = zones.map((zone, i) => {
    const path = arcPath(prev, zone.to);
    prev = zone.to;
    return <path key={i} d={path} fill="none" stroke={zone.color} strokeWidth={strokeWidth} strokeLinecap="butt" />;
  });

  const hasValue = isNum(value);
  const needleAngle = angleOf(hasValue ? value : min);
  const needleTip = pointAt(needleAngle, r - strokeWidth / 2 - 4);

  return (
    <div className="gauge">
      <svg viewBox="0 0 200 110" width="100%">
        {bands}
        {hasValue && (
          <>
            <line x1={cx} y1={cy} x2={needleTip.x} y2={needleTip.y} stroke="var(--text)" strokeWidth={2.5} strokeLinecap="round" />
            <circle cx={cx} cy={cy} r={5} fill="var(--text)" />
          </>
        )}
        <text x={cx - r} y={cy + 16} textAnchor="middle" className="gauge-scale-label">
          {format(min)}
        </text>
        <text x={cx + r} y={cy + 16} textAnchor="middle" className="gauge-scale-label">
          {format(max)}
        </text>
      </svg>
      <div className="gauge-value">{hasValue ? format(value) : "—"}</div>
      <div className="gauge-label">{label}</div>
      {footer}
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
 *  lines. Backed by Schwab regardless of CHAIN_PROVIDER — Tastytrade has
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
            tickFormatter={(v) => formatDateLabel(v, history.range)}
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
          <Tooltip content={<PriceHistoryTooltip range={history.range} />} />
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
      <p className="chart-caption">{RANGE_CAPTION[history.range] ?? RANGE_CAPTION["1M"]} with swing support/resistance</p>
    </>
  );
}

function PriceHistoryTooltip({ active, payload, label, range }) {
  if (!active || !payload || !payload.length) return null;
  const { open, high, low, close } = payload[0].payload;
  const isUp = close >= open;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-price">{formatDateLabel(label, range)}</div>
      <div className={`chart-tooltip-pl ${isUp ? "positive" : "negative"}`}>
        O {open.toFixed(2)} · H {high.toFixed(2)} · L {low.toFixed(2)} · C {close.toFixed(2)}
      </div>
    </div>
  );
}
