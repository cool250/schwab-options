"""Read-only tools the copilot agent can call.

Every tool here is a thin wrapper around an already-existing, already-used
service-layer method (service/position.py, service/transactions.py,
service/market.py) — no new broker calls are written for this feature.

Deliberately NOT wrapped as a tool, on purpose: TastytradeClient.place_order /
.cancel_order / .get_orders (broker/tastytrade/client.py). Those methods
exist in the SDK and default to Tastytrade's PRODUCTION endpoint, but are
unused everywhere else in this app. This agent is read-only — it must never
gain the ability to place, modify, or cancel a real trade.

The OpenAI SDK has no decorator-based auto-schema helper (unlike Anthropic's
@beta_tool), so each tool's JSON schema below is written by hand and must be
kept in sync with the matching function's signature.
"""

import json
import logging
from datetime import date, timedelta

from broker.exceptions import BrokerError
from service import MarketService, PositionService, TransactionService
from service.strategy_builder import ANCHOR_MODES, TEMPLATES, WING_MODES, StrategyParamError

logger = logging.getLogger(__name__)


def _default_date_range(days: int) -> tuple[str, str]:
    end = date.today() + timedelta(days=1)  # see PositionService.get_futures_position for why +1
    start = date.today() - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _safe(fn, *args, **kwargs) -> str:
    """Run a service-layer call and always return a JSON string — a raised
    exception here would break the tool-calling loop, so failures are
    reported back to the model as data instead, letting it explain the
    problem to the user rather than the whole request erroring out."""
    try:
        return json.dumps(fn(*args, **kwargs), default=str)
    except BrokerError as e:
        logger.error("Copilot tool %s failed: %s", getattr(fn, "__qualname__", fn), e)
        return json.dumps({"error": str(e)})


def get_account_balances() -> str:
    return _safe(PositionService().get_balances)


def get_stock_positions() -> str:
    return _safe(PositionService().get_stock_position)


def get_option_positions() -> str:
    puts, calls = PositionService().get_option_position()
    return json.dumps({"puts": puts, "calls": calls}, default=str)


def get_futures_positions(lookback_days: int = 30) -> str:
    return _safe(PositionService().get_futures_position, lookback_days=lookback_days)


def get_futures_option_positions(lookback_days: int = 30) -> str:
    def _fetch(lookback_days: int):
        puts, calls = PositionService().get_futures_option_position(lookback_days=lookback_days)
        return {"puts": puts, "calls": calls}

    return _safe(_fetch, lookback_days)


def get_total_exposure() -> str:
    return _safe(PositionService().get_total_exposure)


def get_option_trade_history(
    ticker: str = "", start_date: str = "", end_date: str = "", realized_gains_only: bool = True
) -> str:
    default_start, default_end = _default_date_range(90)

    def _fetch_and_group(ticker, start_date, end_date, realized_gains_only):
        service = TransactionService()
        trades = service.get_option_transactions(ticker, start_date, end_date, realized_gains_only=realized_gains_only)
        # Merges legs that form a ratio spread (e.g. buy 1 / sell 2+ at a
        # different strike, same underlying/expiration/type, opened together)
        # into one grouped record — see group_ratio_spreads' docstring. Lets
        # the model report an actual ratio-spread position directly instead
        # of inferring the structure itself from a flat leg list.
        return service.group_ratio_spreads(trades)

    return _safe(
        _fetch_and_group,
        ticker,
        start_date or default_start,
        end_date or default_end,
        realized_gains_only,
    )


def get_equity_trade_history(ticker: str = "", start_date: str = "", end_date: str = "") -> str:
    default_start, default_end = _default_date_range(90)
    return _safe(
        TransactionService().get_equity_transactions,
        ticker,
        start_date or default_start,
        end_date or default_end,
    )


def get_price_history(symbol: str, days: int = 30) -> str:
    return _safe(MarketService().get_price_history, symbol, days)


def get_option_chain(symbol: str, dte: int = 7, strike_count: int = 20) -> str:
    return _safe(MarketService().get_option_chain, symbol, dte, strike_count)


def get_expirations(symbol: str, days_ahead: int = 60) -> str:
    return _safe(MarketService().get_expirations, symbol, days_ahead)


# Strategies the copilot may build: credit templates only, matching the
# net-credit HARD CONSTRAINT in agent.py's system prompt. The Analyze page's
# builder overlay offers the debit templates too; widening this tuple is
# the one change needed if the copilot's rule ever changes.
COPILOT_STRATEGY_DIRECTIONS = ("credit",)
COPILOT_STRATEGIES = [k for k, t in TEMPLATES.items() if t["direction"] in COPILOT_STRATEGY_DIRECTIONS]


def build_strategy(
    symbol: str,
    strategy: str,
    dte: int,
    expiration_date: str = "",
    params: dict | None = None,
    min_credit: float | None = None,
    max_dte: int | None = None,
) -> str:
    """Place a named strategy's legs on the live chain — the same solver as
    the Analyze page's Strategy Builder (service/strategy_builder.py)."""
    strategy = strategy.strip().upper()
    if strategy not in COPILOT_STRATEGIES:
        return json.dumps({"error": f"Unsupported strategy {strategy!r}; use one of {COPILOT_STRATEGIES}"})
    symbol = symbol.strip().upper()
    try:
        result = MarketService().build_strategy(
            symbol, dte, strategy, params or {}, min_credit, expiration_date or None, max_dte
        )
    except StrategyParamError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:  # e.g. TastytradeAPIError, which isn't a BrokerError — never break the tool loop
        logger.error("Copilot build_strategy failed for %s %s: %s", symbol, strategy, e)
        return json.dumps({"error": str(e) or e.__class__.__name__})
    if result is None:
        return json.dumps({"error": f"No option chain found for {symbol}"})
    return json.dumps(result, default=str)


def _strategy_legs_doc() -> str:
    """One line per buildable strategy listing its leg keys and roles, for
    build_strategy's schema description — generated so it can't drift from
    the templates."""
    lines = []
    for key in COPILOT_STRATEGIES:
        legs = ", ".join(
            f'{leg["key"]} ({leg["role"]}, default {leg["default"]["mode"]}'
            + (f' {leg["default"]["value"]}' if leg["default"].get("value") is not None else "")
            + ")"
            if leg["role"] != "same"
            else f'{leg["key"]} (same strike as {leg["of"]})'
            for leg in TEMPLATES[key]["legs"]
        )
        lines.append(f"{key}: {legs}")
    return "\n".join(lines)


def propose_legs(legs: list[dict]) -> str:
    """Not a data fetch like every other tool here — this one has no broker
    call at all. Calling it is how the model hands a concrete, actionable
    recommendation to the frontend: agent.chat() intercepts this call by
    name and returns `legs` to the caller as `proposed_legs`, which
    CopilotWidget renders as an "Apply to StrikeLab" button. The return
    value here only goes back into the model's own conversation (so the
    tool-calling loop has something to continue on), not to the user."""
    return json.dumps({"status": "proposed", "count": len(legs)})


TOOL_FUNCTIONS = {
    "get_account_balances": get_account_balances,
    "get_stock_positions": get_stock_positions,
    "get_option_positions": get_option_positions,
    "get_futures_positions": get_futures_positions,
    "get_futures_option_positions": get_futures_option_positions,
    "get_total_exposure": get_total_exposure,
    "get_option_trade_history": get_option_trade_history,
    "get_equity_trade_history": get_equity_trade_history,
    "get_price_history": get_price_history,
    "get_option_chain": get_option_chain,
    "get_expirations": get_expirations,
    "build_strategy": build_strategy,
    "propose_legs": propose_legs,
}

# OpenAI chat-completions "tools" format: one {"type": "function", "function": {...}}
# entry per tool, JSON-schema parameters.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_account_balances",
            "description": "Get the user's Schwab account balances: cash balance, total account "
            "(liquidation) value, and mutual fund value.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_positions",
            "description": "Get the user's currently open equity/ETF stock positions, each with "
            "symbol, quantity, average trade price, and current price.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_option_positions",
            "description": "Get the user's currently open equity option positions (calls and "
            "puts), each with ticker, strike, expiration, days-to-expiry, quantity, trade price, "
            "current price, and dollar exposure (puts only).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_futures_positions",
            "description": "Get the user's currently open futures positions (e.g. /ES, /NQ). "
            "Reconstructed from transaction history since Schwab doesn't expose futures in its "
            "positions endpoint, so this only sees trades within lookback_days — a position "
            "opened earlier than that won't show up here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "How many days of transaction history to scan for still-open futures trades.",
                        "default": 30,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_futures_option_positions",
            "description": "Get the user's currently open futures-option positions (options on "
            "/ES, /NQ, etc.), split into puts and calls. Same transaction-history reconstruction "
            "and lookback_days caveat as get_futures_positions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "How many days of transaction history to scan for still-open futures-option trades.",
                        "default": 30,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_total_exposure",
            "description": "Get the user's total short-put dollar exposure, grouped by underlying "
            "ticker — how much capital would be required if every open short put were assigned.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_option_trade_history",
            "description": "Get the user's equity-option trade history with matched open/close "
            "legs and realized P&L. Defaults to the last 90 days across all tickers if no dates "
            "are given. Legs that form a ratio spread (buy 1 / sell 2+ at a different strike, "
            "same underlying/expiration/type, opened together) are already merged into a single "
            "record with \"strategy\": \"RATIO_SPREAD\" (its \"type\" still holds the normal "
            "CLOSED/EXPIRED/ASSIGNED status), a \"ratio\" like \"1:2\", \"long_leg\"/\"short_leg\" "
            "strikes, and one combined total_amount — report those as one position, don't "
            "re-derive the grouping yourself from individual legs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": 'Ticker symbol to filter by, e.g. "AAPL" — empty string means all tickers.',
                        "default": "",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date as YYYY-MM-DD — defaults to 90 days ago if omitted.",
                        "default": "",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date as YYYY-MM-DD — defaults to today if omitted.",
                        "default": "",
                    },
                    "realized_gains_only": {
                        "type": "boolean",
                        "description": "If true (default), only return closed trades; if false, include still-open ones too.",
                        "default": True,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_equity_trade_history",
            "description": "Get the user's equity/futures trade history, FIFO-matched into round "
            "trips with realized P&L. Defaults to the last 90 days across all tickers if no dates "
            "are given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": 'Ticker symbol to filter by, e.g. "AAPL" — empty string means all tickers.',
                        "default": "",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date as YYYY-MM-DD — defaults to 90 days ago if omitted.",
                        "default": "",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date as YYYY-MM-DD — defaults to today if omitted.",
                        "default": "",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Get daily OHLC price candles for a symbol over the last N days, plus "
            "computed support and resistance levels from recent swing highs/lows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": 'Ticker symbol, e.g. "AAPL" or "/ES" for a futures root.'},
                    "days": {
                        "type": "integer",
                        "description": "How many calendar days of history to return.",
                        "default": 30,
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_option_chain",
            "description": "Get a normalized options chain (calls and puts merged by strike, "
            "with bid/ask/delta) for the expiration closest to dte days out. The default "
            "strike_count (20) can fail to reach a strike with the delta you're actually looking "
            "for — the broker returns the N strikes closest to spot in total, not a guaranteed "
            "count on each side, so the window can be lopsided, and a short-DTE contract's delta "
            "can still be well above your target many strikes out. If you don't find a strike "
            "matching what you need (a delta ceiling, a strike below/above another leg, etc.) in "
            "the returned chain, call again with a larger strike_count (e.g. double it) before "
            "concluding no such strike exists — don't declare 'no valid configuration is "
            "available' off a single default-sized fetch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": 'Ticker symbol, e.g. "AAPL" or "/ES" for a futures root.'},
                    "dte": {
                        "type": "integer",
                        "description": "Target days-to-expiration — the closest actual expiration is used.",
                        "default": 7,
                    },
                    "strike_count": {
                        "type": "integer",
                        "description": "Number of strikes above/below the current price to request — not a "
                        "guaranteed count on each side (see the tool description). Increase this and call "
                        "again if the first response doesn't include a strike matching what you need.",
                        "default": 20,
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expirations",
            "description": "Get every listed option expiration date for a symbol within the next "
            "days_ahead days, each with its days-to-expiration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": 'Ticker symbol, e.g. "AAPL" or "/ES" for a futures root.'},
                    "days_ahead": {
                        "type": "integer",
                        "description": "Only include expirations within this many days from today.",
                        "default": 60,
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_strategy",
            "description": "Place a named multi-leg (or single-leg) credit strategy on the live option "
            "chain for one expiration: finds the strikes matching the requested placement (delta, "
            "% OTM, expected move, strike, wing width), searches up to 5 strikes either way when "
            "the strategy's structure or min_credit isn't met, and returns the best match plus "
            "alternatives with legs (bid/ask/mid/delta/iv), netPremium (credit at mid, per share), "
            "naturalPremium (credit selling at the bid and buying at the ask, per share), maxProfit, "
            "maxLoss (null = unlimited), breakevens, pop (estimated probability of profit) and "
            "returnOnRisk (maxProfit / |maxLoss|). best is null when nothing qualifies, with "
            "`reasons` saying why. It only places strikes and enforces each strategy's structure "
            "(strike order, net credit, a jade lizard's credit covering its call spread); the "
            "strategy reference's own rules (covering checks, delta ceilings, ratio floors) still "
            "apply and must be checked against the result. Strategies and their leg keys:\n"
            + _strategy_legs_doc(),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": 'Ticker symbol, e.g. "AAPL" or "/ES" for a futures root.'},
                    "strategy": {"type": "string", "enum": COPILOT_STRATEGIES},
                    "dte": {
                        "type": "integer",
                        "description": "Days to expiration of the chosen expiration (the closest listed "
                        "expiration is used).",
                    },
                    "expiration_date": {
                        "type": "string",
                        "description": "The chosen expiration as YYYY-MM-DD, if known — the result's reasons "
                        "flag it if the chain resolved to a different date.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional placement per leg key (see the strategy list above); legs "
                        "left out use their default. Anchor legs take mode "
                        f"{'/'.join(ANCHOR_MODES)}; wing legs take mode {'/'.join(WING_MODES)}. Delta is a "
                        "fraction (0.16, not 16); otm_pct is percent out of the money; sigma is a multiple "
                        "of the expected move from the chain's IV; width is in dollars; steps is a count of "
                        "listed strikes; atm takes no value.",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "mode": {"type": "string", "enum": sorted(set(ANCHOR_MODES) | set(WING_MODES))},
                                "value": {"type": "number"},
                            },
                            "required": ["mode"],
                        },
                    },
                    "min_credit": {
                        "type": "number",
                        "description": "Optional minimum net credit per share at mid (e.g. 1.50).",
                    },
                    "max_dte": {
                        "type": "integer",
                        "description": "Optional end of an expiration range: builds on every listed "
                        "expiration with days-to-expiration from dte through max_dte (at most 10 "
                        "expirations) and ranks them together — each candidate then carries its own "
                        "expirationDate/dte, and the alternatives include the best match on each other "
                        "expiration. Omit to build on a single expiration (and always omit it when the "
                        "page context gives a selectedExpirationDte).",
                    },
                },
                "required": ["symbol", "strategy", "dte"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_legs",
            "description": "Record one or more concrete option legs you're recommending, so the "
            "user can apply them to the StrikeLab chart with one click instead of re-entering "
            "them by hand. Call this whenever you give a specific, actionable strike/expiration "
            "recommendation — in addition to explaining your reasoning in your normal reply, not "
            "instead of it. Don't call it for purely educational or hypothetical discussion (e.g. "
            "\"what is a put ratio spread\") where no real strikes were actually chosen. This "
            "does not place, modify, or preview any real order — it only stages a position in "
            "the app's own analysis tool, and the user still has to click Apply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "legs": {
                        "type": "array",
                        "description": "One or more legs forming the recommended position, same "
                        "underlying and expiration unless the strategy genuinely spans more than one.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {
                                    "type": "string",
                                    "description": 'Underlying ticker, e.g. "AAPL" or "/ES" for a futures root.',
                                },
                                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                                "optionType": {"type": "string", "enum": ["CALL", "PUT"]},
                                "strike": {"type": "number"},
                                "quantity": {
                                    "type": "integer",
                                    "description": "Number of contracts, always positive — side conveys direction.",
                                    "minimum": 1,
                                },
                                "premium": {
                                    "type": "number",
                                    "description": "Estimated entry price per contract (e.g. the chain's mid price).",
                                },
                                "dte": {
                                    "type": "integer",
                                    "description": "Days to expiration, matching the chosen expiration.",
                                },
                                "expirationDate": {
                                    "type": "string",
                                    "description": "Expiration date as YYYY-MM-DD.",
                                },
                            },
                            "required": ["symbol", "side", "optionType", "strike", "quantity", "premium", "dte", "expirationDate"],
                        },
                    },
                },
                "required": ["legs"],
            },
        },
    },
]
