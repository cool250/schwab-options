import React, { useState, useMemo, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
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
import { getExpirationList, friendlyErrorMessage } from "../api/client";
import { MULTIPLIER, getMultiplier } from "../utils/contractMultiplier";
import { symbolStore } from "../utils/symbolStore";

/** Patches a live bid/ask tick into whichever leg (call or put, on whichever
 *  strike row) carries that streamer-symbol, leaving everything else as-is. */
function patchChainQuote(chain, msg) {
  if (!chain) return chain;
  let anyChanged = false;
  const rows = chain.chain.map((row) => {
    const callMatch = row.call && row.call.symbol === msg.symbol;
    const putMatch = row.put && row.put.symbol === msg.symbol;
    if (!callMatch && !putMatch) return row;
    anyChanged = true;
    return {
      ...row,
      call: callMatch ? { ...row.call, bid: msg.bid, ask: msg.ask } : row.call,
      put: putMatch ? { ...row.put, bid: msg.bid, ask: msg.ask } : row.put,
    };
  });
  return anyChanged ? { ...chain, chain: rows } : chain;
}

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

function legPL(leg, price) {
  const intrinsic =
    leg.type === "CALL" ? Math.max(0, price - leg.strike) : Math.max(0, leg.strike - price);
  const perShare = leg.side === "BUY" ? intrinsic - leg.premium : leg.premium - intrinsic;
  return perShare * leg.qty * (leg.multiplier ?? MULTIPLIER);
}

function totalPL(legs, price) {
  return legs.reduce((sum, leg) => sum + legPL(leg, price), 0);
}

function netCredit(legs) {
  return legs.reduce(
    (sum, leg) => sum + (leg.side === "SELL" ? 1 : -1) * leg.premium * leg.qty * (leg.multiplier ?? MULTIPLIER),
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
  return perShare * leg.qty * (leg.multiplier ?? MULTIPLIER);
}

function totalTheoPL(legs, price, dte, iv) {
  return legs.reduce((sum, leg) => sum + legTheoPL(leg, price, dte, iv), 0);
}

/** Builds the strike x date P&L grid used by the Table view. */
function buildPLTable(legs, spot, lo, hi, maxDte, iv, chainStrikes, rows = 16, cols = 8) {
  // Row prices are the option chain's own real strikes within [lo, hi]
  // (highest first, same order the synthetic grid used) rather than an
  // arbitrary evenly-spaced price grid — so each row lines up with a
  // contract that actually exists. Falls back to the old evenly-spaced grid
  // if the chain hasn't loaded yet (or has nothing in range), same "sample
  // down to at most `rows`, keep both ends" approach as the date columns.
  const strikesInRange = (chainStrikes ?? []).filter((s) => s >= lo && s <= hi).sort((a, b) => b - a);
  let prices;
  if (strikesInRange.length > 0) {
    if (strikesInRange.length > rows) {
      const idxStep = (strikesInRange.length - 1) / (rows - 1);
      const seenIdx = new Set();
      prices = [];
      for (let i = 0; i < rows; i++) {
        const idx = Math.round(i * idxStep);
        if (!seenIdx.has(idx)) {
          seenIdx.add(idx);
          prices.push(strikesInRange[idx]);
        }
      }
    } else {
      prices = strikesInRange;
    }
  } else {
    const step = (hi - lo) / (rows - 1);
    prices = Array.from({ length: rows }, (_, i) => +(hi - i * step).toFixed(2));
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Only weekday calendar dates are real trading/decay days — weekends are
  // skipped entirely (never shown as a column) rather than displaying a date
  // where nothing actually changes. dte counts down from maxDte (today) to
  // 0 (expiration), so each dte's calendar date is today + (maxDte - dte).
  const weekdayEntries = [];
  for (let d = maxDte; d >= 0; d--) {
    const date = new Date(today);
    date.setDate(date.getDate() + (maxDte - d));
    const dow = date.getDay();
    if (dow !== 0 && dow !== 6) weekdayEntries.push({ dte: d, date });
  }

  // Evenly sample down to at most `cols` weekday entries — always keeping
  // the first (today) and last (expiration, or the nearest weekday to it).
  let sampled = weekdayEntries;
  if (weekdayEntries.length > cols) {
    const idxStep = (weekdayEntries.length - 1) / (cols - 1);
    const seenIdx = new Set();
    sampled = [];
    for (let i = 0; i < cols; i++) {
      const idx = Math.round(i * idxStep);
      if (!seenIdx.has(idx)) {
        seenIdx.add(idx);
        sampled.push(weekdayEntries[idx]);
      }
    }
  }

  const grid = prices.map((price) => ({
    price,
    values: sampled.map(({ dte }) => totalTheoPL(legs, price, dte, iv)),
  }));
  return { dateCols: sampled.map((s) => s.date), grid };
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
      leg.type === "CALL" ? sum + (leg.side === "BUY" ? 1 : -1) * leg.qty * (leg.multiplier ?? MULTIPLIER) : sum,
    0
  );
  if (callSlope < 0) minP = -Infinity;

  return { maxProfit: maxP, maxLoss: minP };
}

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

// Bid/ask/delta from the backend are usually a number or null/undefined, but
// a stray non-numeric value (e.g. dxFeed's "NaN" sentinel string slipping
// through unsanitized) has crashed the whole chain table before — `!= null`
// alone doesn't catch that, and calling .toFixed() on a string throws with
// no error boundary anywhere in the app to stop it taking down the page.
const isNum = (x) => typeof x === "number" && Number.isFinite(x);

// A leg's premium always comes from the mid of bid/ask (not whichever side
// happened to be clicked/dragged to) — a fill at the raw bid or ask assumes
// the worst side of the spread, which overstates credit or understates cost
// for what's meant to be a neutral analysis tool. Falls back to whichever
// single side is available if the other is missing.
function midPrice(sideData) {
  const bid = sideData?.bid;
  const ask = sideData?.ask;
  if (isNum(bid) && isNum(ask)) return (bid + ask) / 2;
  if (isNum(bid)) return bid;
  if (isNum(ask)) return ask;
  return null;
}

/* ============================================================================
   MAIN PAGE
============================================================================ */

// Survives unmounting/remounting this page (e.g. navigating to Positions and
// back) within the same browser session — only a full page reload, typing a
// new symbol, or a fresh "Analyze Selected" from Positions replaces it.
const strikeLabCache = {
  symbol: null,
  symbolInput: null,
  spot: null,
  expIndex: null,
  legs: null,
  rangePct: null,
  ivPct: null,
  chain: null,
  view: null,
  expirations: null,
};

export default function StrikeLab() {
  const location = useLocation();
  // Positions selected on the Positions page arrive once, via router state, as
  // { analyzePositions: [{ symbol, strike, optionType, quantity, premium, dte }, ...], view }.
  // Snapshotted at mount only — added as legs below, then cleared so a later
  // re-render (or manual edit) doesn't re-add them. Arriving this way counts
  // as a deliberate new search, so it wins over whatever's cached below.
  const pendingPositions = useRef(location.state?.analyzePositions ?? []);
  const isNewAnalyzeRequest = pendingPositions.current.length > 0;

  // symbolStore is shared with the Charts page (and always has a value, its
  // own default included) — it takes priority over this page's own cache so
  // switching symbol on either page carries over to the other, but an
  // explicit "Analyze Selected" request (pendingPositions) always wins over
  // both since it's a deliberate new symbol.
  const [symbol, setSymbol] = useState(pendingPositions.current[0]?.symbol || symbolStore.symbol);
  const [symbolInput, setSymbolInput] = useState(pendingPositions.current[0]?.symbol || symbolStore.symbol);
  const [spot, setSpot] = useState(strikeLabCache.spot ?? DEFAULT_SPOT);
  const [expIndex, setExpIndex] = useState(strikeLabCache.expIndex ?? 0);
  const [legs, setLegs] = useState(isNewAnalyzeRequest ? [] : strikeLabCache.legs ?? []);
  const [rangePct, setRangePct] = useState(strikeLabCache.rangePct ?? 3.6);
  const [ivPct, setIvPct] = useState(strikeLabCache.ivPct ?? 10.9);
  const [chain, setChain] = useState(strikeLabCache.chain ?? null);
  const [loadingChain, setLoadingChain] = useState(false);
  const [chainError, setChainError] = useState(null);
  const [view, setView] = useState(location.state?.view || strikeLabCache.view || "chain"); // 'chain' | 'table' | 'graph'

  // Skip the initial network fetch when we're restoring the same symbol's
  // already-cached expirations rather than starting a genuinely new search —
  // otherwise every remount would silently refetch and briefly flash a
  // reload over data that hasn't actually changed. The chain itself doesn't
  // need an equivalent guard: the WebSocket subscription below renders
  // whatever's cached immediately and only replaces it once a fresh
  // snapshot actually arrives, so reconnecting is never a visible reload.
  const skipInitialExpirationsFetch = useRef(
    !isNewAnalyzeRequest && strikeLabCache.symbol === symbol && (strikeLabCache.expirations?.length ?? 0) > 0
  );

  const [expirations, setExpirations] = useState(strikeLabCache.expirations ?? []); // [{date, dte}] — real listed expirations, incl. daily where offered
  const dte = expirations[expIndex]?.dte;
  // The pill above only controls which chain you're browsing to add new legs —
  // an already-built position keeps the expiration it was actually added at,
  // so time decay (Table/Graph) must track the legs' own dte, not the pill.
  // Use the most recently added leg: if legs span multiple expirations, the
  // latest one reflects what you're currently building toward.
  const positionDte = legs.length > 0 ? legs[legs.length - 1].dte : dte;

  // Add any positions selected on the Positions page as legs, once, on mount —
  // replacing whatever legs were cached from an earlier, unrelated visit,
  // since arriving this way is itself the new search. Each keeps its own dte
  // (independent of the expiration pill above, same as any manually-added
  // leg) rather than snapping to a listed expiration — note this means legs
  // from different underlyings can end up mixed together, even though the
  // payoff math below only prices one spot.
  useEffect(() => {
    const positions = pendingPositions.current;
    if (positions.length === 0) return;
    setLegs(
      positions.map((p, i) => ({
        id: `l${Date.now()}-${i}`,
        side: p.quantity < 0 ? "SELL" : "BUY",
        qty: Math.abs(p.quantity) || 1,
        type: p.optionType,
        strike: p.strike,
        premium: p.premium,
        dte: p.dte,
        multiplier: getMultiplier(p.symbol),
      }))
    );
    pendingPositions.current = [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (skipInitialExpirationsFetch.current) {
      skipInitialExpirationsFetch.current = false;
      return;
    }
    if (!symbol) {
      setExpirations([]);
      setChainError(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await getExpirationList(symbol);
        // Sorted by dte ascending — cap to the next 10 so the pill row renders cleanly.
        if (!cancelled) {
          setExpirations((result || []).slice(0, 10));
          setChainError(null);
        }
      } catch (e) {
        console.error("Failed to load expirations:", e);
        if (!cancelled) {
          setExpirations([]);
          setChainError(friendlyErrorMessage(e, e.message || "Failed to load expirations."));
        }
      }
      if (!cancelled) setExpIndex(0);
    })();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  // Live chain feed: opens one WebSocket per symbol/dte, gets a full snapshot
  // back immediately (same shape the old one-shot REST call returned), then
  // keeps receiving individual bid/ask ticks as the market moves — no more
  // re-fetching the whole chain to see a fresher price. Reconnects with
  // backoff if the connection drops (dev-server restarts, brief network
  // blips, etc.); the effect's cleanup closes it on symbol/dte change or unmount.
  useEffect(() => {
    if (dte == null) return;

    let cancelled = false;
    let socket = null;
    let reconnectTimer = null;
    let retryDelayMs = 1000;

    function connect() {
      const token = sessionStorage.getItem("auth_token");
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(
        `${proto}://${window.location.host}/api/market/ws/chain?token=${encodeURIComponent(token ?? "")}`
      );

      socket.onopen = () => {
        retryDelayMs = 1000;
        socket.send(JSON.stringify({ action: "subscribe", symbol, dte, strike_count: 20 }));
      };

      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") {
          setChain(msg.chain);
          setSpot(msg.chain.spot);
          // Some brokers (e.g. Tastytrade) don't expose chain-level IV — keep
          // whatever IV is already set rather than zeroing it out.
          if (msg.chain.iv != null) setIvPct(msg.chain.iv * 100);
          setLoadingChain(false);
          setChainError(null);
        } else if (msg.type === "quote") {
          setChain((prev) => patchChainQuote(prev, msg));
        } else if (msg.type === "error") {
          // The chain view falls back to whatever's already rendered (cached
          // or a prior snapshot) rather than clearing to a blank state, but
          // still surfaces the failure instead of hanging silently.
          console.error("Chain stream error:", msg.message || msg);
          setLoadingChain(false);
          setChainError(msg.message || "Failed to load chain data.");
        }
      };

      socket.onclose = (event) => {
        if (cancelled) return;
        // 4401: token rejected/expired server-side (api/market_stream.py) —
        // retrying with the same stale token would just loop forever, so
        // send the user back through the same re-auth path the REST client
        // uses on a 401 instead.
        if (event.code === 4401) {
          sessionStorage.removeItem("auth_token");
          window.location.href = "/login";
          return;
        }
        reconnectTimer = setTimeout(connect, retryDelayMs);
        retryDelayMs = Math.min(retryDelayMs * 2, 15000);
      };

      socket.onerror = () => socket.close();
    }

    setLoadingChain(true);
    setChainError(null);
    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [symbol, dte]);

  // Keep the cache in sync with every field it tracks, so a later
  // unmount/remount of this page picks up right where things were left.
  useEffect(() => {
    symbolStore.symbol = symbol;
    strikeLabCache.symbol = symbol;
    strikeLabCache.symbolInput = symbolInput;
    strikeLabCache.spot = spot;
    strikeLabCache.expIndex = expIndex;
    strikeLabCache.legs = legs;
    strikeLabCache.rangePct = rangePct;
    strikeLabCache.ivPct = ivPct;
    strikeLabCache.chain = chain;
    strikeLabCache.view = view;
    strikeLabCache.expirations = expirations;
  }, [symbol, symbolInput, spot, expIndex, legs, rangePct, ivPct, chain, view, expirations]);

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
        multiplier: getMultiplier(symbol),
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
      return [
        ...prev,
        { id: `l${Date.now()}`, side, qty: 1, type, strike, premium: +premium.toFixed(2), dte, multiplier: getMultiplier(symbol) },
      ];
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

      {chainError && <div className="alert error">{chainError}</div>}

      {/* ---------------- Symbol / strategy / expirations / ruler ---------------- */}
      <div className="card">
        <div className="symbol-exp-row">
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
            {symbol && (
              <span className="price-badge ok">
                Current price: ${spot.toFixed(2)}
                {loadingChain && <span className="spinner spinner-sm" title="Syncing chain…" />}
              </span>
            )}
          </div>

          <div className="exp-group">
            <span className="metric-label">Expiration{dte != null ? ` · ${dte}d` : ""}</span>
            <div className="exp-pills">
              {expirations.length === 0 && (
                <span className="text-muted">
                  {!symbol ? "Enter a symbol to get started" : chainError ? "Failed to load expirations" : "Loading expirations…"}
                </span>
              )}
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
        <StrikeRuler legs={legs} spot={spot} lo={lo} hi={hi} chain={chain} onUpdateLeg={updateLeg} />
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
      <div className="card metrics-card--compact">
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
              {breakevens.length > 0 && (
                <span className="text-muted metric-subtext">
                  {" "}({(((breakevens[0] - spot) / spot) * 100).toFixed(1)}% from spot)
                </span>
              )}
            </span>
          </div>
        </div>
      </div>

      {/* ---------------- Chain / Table / Graph ---------------- */}
      <div className="card">
        <div className="tab-row">
          {[
            { id: "chain", label: "Chain" },
            { id: "table", label: "Table" },
            { id: "graph", label: "Graph" },
          ].map((t) => (
            <button
              key={t.id}
              className={`tab-item ${view === t.id ? "active" : ""}`}
              onClick={() => setView(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {positionDte == null ? (
          <div className="chain-empty">{!symbol ? "Enter a symbol to get started" : "Loading expirations…"}</div>
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
                {/* Animation off: chartData recomputes on every leg edit keystroke
                    and every tick of the Range slider drag (uncapped, fires
                    dozens of times/sec) — re-triggering a 700ms animated redraw
                    on each one is what made this feel slow, not the underlying
                    140-point payoff calc, which is cheap. */}
                <Area
                  dataKey="pos"
                  stroke="var(--success)"
                  strokeWidth={2}
                  fill="url(#payoffPos)"
                  isAnimationActive={false}
                  dot={false}
                />
                <Area
                  dataKey="neg"
                  stroke="var(--error)"
                  strokeWidth={2}
                  fill="url(#payoffNeg)"
                  isAnimationActive={false}
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
            chain={chain}
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
        <div className="slider-row-pair">
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
      </div>
    </div>
  );
}

/* ============================================================================
   Strike ruler — horizontal number line with leg markers, draggable to
   re-strike a leg. Dragging a tag snaps to the nearest strike actually
   listed on the live chain (not an arbitrary price) and pulls that strike's
   real bid/ask from the chain into the leg's premium — same BUY=ask/
   SELL=bid convention as clicking a cell directly in the chain table
   (see addLegFromChain/OptionChainTable's onAddLeg calls).
============================================================================ */
function StrikeRuler({ legs, spot, lo, hi, chain, onUpdateLeg }) {
  const width = 100;
  const strikes = legs.map((l) => l.strike);
  const effLo = Math.min(lo, ...strikes);
  const effHi = Math.max(hi, ...strikes);
  const pct = (price) => ((price - effLo) / (effHi - effLo)) * width;
  const priceFromPct = (p) => effLo + (p / width) * (effHi - effLo);
  const ticks = [];
  const tickStep = (effHi - effLo) / 8;
  for (let i = 0; i <= 8; i++) ticks.push(effLo + i * tickStep);

  const trackRef = useRef(null);
  const [draggingId, setDraggingId] = useState(null);

  const availableStrikes = useMemo(
    () => [...new Set((chain?.chain ?? []).map((r) => r.strikePrice))].sort((a, b) => a - b),
    [chain]
  );

  function nearestStrike(price) {
    if (availableStrikes.length === 0) return price;
    return availableStrikes.reduce((best, s) => (Math.abs(s - price) < Math.abs(best - price) ? s : best));
  }

  // Mid of bid/ask — same convention the chain table itself uses when a
  // bid/ask cell is clicked to add a leg (see midPrice). Returns null
  // (leaving premium untouched) if this strike has no live quote at all,
  // rather than snapping premium to 0.
  function premiumForStrike(strike, type) {
    const row = (chain?.chain ?? []).find((r) => r.strikePrice === strike);
    const sideData = type === "PUT" ? row?.put : row?.call;
    return midPrice(sideData);
  }

  useEffect(() => {
    if (draggingId == null || !onUpdateLeg) return;

    function handleMove(e) {
      const track = trackRef.current;
      if (!track) return;
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const rect = track.getBoundingClientRect();
      const pctPos = Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100));
      const snapped = nearestStrike(priceFromPct(pctPos));
      const leg = legs.find((l) => l.id === draggingId);
      if (!leg || leg.strike === snapped) return;
      const newPremium = premiumForStrike(snapped, leg.type);
      onUpdateLeg(draggingId, { strike: snapped, ...(newPremium != null ? { premium: newPremium } : {}) });
    }
    function handleUp() {
      setDraggingId(null);
    }

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    window.addEventListener("touchmove", handleMove);
    window.addEventListener("touchend", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      window.removeEventListener("touchmove", handleMove);
      window.removeEventListener("touchend", handleUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draggingId, legs, availableStrikes]);

  // Legs sharing the same (strike, side) — e.g. a short straddle's SELL
  // call + SELL put at one strike — would otherwise render exactly on top
  // of each other (same left AND same top). Stack duplicates further from
  // the ruler line instead, one below the other, so every leg stays visible.
  const stackCounts = {};
  const stackIndexById = {};
  legs.forEach((leg) => {
    const key = `${leg.strike}|${leg.side}`;
    const idx = stackCounts[key] ?? 0;
    stackCounts[key] = idx + 1;
    stackIndexById[leg.id] = idx;
  });
  const STACK_STEP_PX = 26;

  return (
    <div className="strike-ruler">
      <span className="metric-label">Strikes</span>
      <div className="ruler-track" ref={trackRef}>
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
        {legs.map((leg) => {
          const stackIdx = stackIndexById[leg.id] ?? 0;
          const stackOffset = stackIdx * STACK_STEP_PX;
          return (
            <div
              key={leg.id}
              className={`ruler-tag ${leg.side === "SELL" ? "tag-sell tag-below" : "tag-buy tag-above"} tag-${leg.type.toLowerCase()} ${draggingId === leg.id ? "ruler-tag-dragging" : ""}`}
              style={{
                left: `${pct(leg.strike)}%`,
                top: leg.side === "SELL" ? `calc(34px + ${stackOffset}px)` : `calc(-44px - ${stackOffset}px)`,
                cursor: onUpdateLeg ? "ew-resize" : undefined,
              }}
              onMouseDown={onUpdateLeg ? (e) => { e.preventDefault(); setDraggingId(leg.id); } : undefined}
              onTouchStart={onUpdateLeg ? () => setDraggingId(leg.id) : undefined}
              title={onUpdateLeg ? "Drag to change strike" : undefined}
            >
              {leg.strike}
              {leg.type[0]}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ============================================================================
   Table view — strike x date theta-decay heatmap
============================================================================ */
// Text color is deliberately left to CSS (.pl-value uses var(--text)) rather
// than set here — that token is already dark in light mode / light in dark
// mode, which is exactly "black in normal mode, white in dark mode" without
// hardcoding a theme check in JS.
function cellColor(value, maxProfit, maxLoss) {
  if (value >= 0) {
    const t = maxProfit > 0 ? Math.min(1, value / maxProfit) : 0;
    const alpha = 0.08 + t * 0.55;
    return { background: `rgba(5, 150, 105, ${alpha})` };
  }
  const t = maxLoss < 0 ? Math.min(1, value / maxLoss) : 0;
  const alpha = 0.08 + t * 0.55;
  return { background: `rgba(220, 38, 38, ${alpha})` };
}

function PLTable({ legs, spot, lo, hi, dte, iv, maxProfit, maxLoss, chain }) {
  const chainStrikes = useMemo(() => (chain?.chain ?? []).map((r) => r.strikePrice), [chain]);
  const { dateCols, grid } = useMemo(
    () => buildPLTable(legs, spot, lo, hi, dte, iv, chainStrikes, 16, 8),
    [legs, spot, lo, hi, dte, iv, chainStrikes]
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
        <div className="pl-heatmap" style={{ gridTemplateColumns: `70px repeat(${dateCols.length}, 1fr)` }}>
          <div className="pl-cell pl-corner">Strike</div>
          {dateCols.map((date, i) => (
            <div key={i} className="pl-cell pl-colhead">
              {date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
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
                    style={{ background: style.background }}
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
                <span className="chain-delta">{isNum(row.call?.delta) ? row.call.delta.toFixed(2) : "—"}</span>
                <span
                  className={`chain-bid ${isNum(row.call?.bid) ? "" : "chain-disabled"}`}
                  onClick={() => isNum(row.call?.bid) && onAddLeg("CALL", "SELL", row.strikePrice, midPrice(row.call))}
                  title={isNum(row.call?.bid) ? "Sell a call at mid" : undefined}
                >
                  {isNum(row.call?.bid) ? row.call.bid.toFixed(2) : "—"}
                </span>
                <span
                  className={`chain-ask ${isNum(row.call?.ask) ? "" : "chain-disabled"}`}
                  onClick={() => isNum(row.call?.ask) && onAddLeg("CALL", "BUY", row.strikePrice, midPrice(row.call))}
                  title={isNum(row.call?.ask) ? "Buy a call at mid" : undefined}
                >
                  {isNum(row.call?.ask) ? row.call.ask.toFixed(2) : "—"}
                </span>
                <span className="chain-strike">{row.strikePrice}</span>
                <span
                  className={`chain-bid ${isNum(row.put?.bid) ? "" : "chain-disabled"}`}
                  onClick={() => isNum(row.put?.bid) && onAddLeg("PUT", "SELL", row.strikePrice, midPrice(row.put))}
                  title={isNum(row.put?.bid) ? "Sell a put at mid" : undefined}
                >
                  {isNum(row.put?.bid) ? row.put.bid.toFixed(2) : "—"}
                </span>
                <span
                  className={`chain-ask ${isNum(row.put?.ask) ? "" : "chain-disabled"}`}
                  onClick={() => isNum(row.put?.ask) && onAddLeg("PUT", "BUY", row.strikePrice, midPrice(row.put))}
                  title={isNum(row.put?.ask) ? "Buy a put at mid" : undefined}
                >
                  {isNum(row.put?.ask) ? row.put.ask.toFixed(2) : "—"}
                </span>
                <span className="chain-delta">{isNum(row.put?.delta) ? row.put.delta.toFixed(2) : "—"}</span>
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

