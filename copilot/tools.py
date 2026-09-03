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

from broker.schwab.exceptions import BrokerError
from service import MarketService, PositionService, TransactionService

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
    return _safe(
        TransactionService().get_option_transactions,
        ticker,
        start_date or default_start,
        end_date or default_end,
        realized_gains_only=realized_gains_only,
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
            "with bid/ask/delta) for the expiration closest to dte days out.",
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
                        "description": "Number of strikes above/below the current price to include.",
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
]
