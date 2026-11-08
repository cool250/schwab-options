"""The copilot agent: system prompt assembly + the OpenAI tool-calling loop.

The core `openai` package has no built-in agentic-loop helper (unlike
Anthropic's Tool Runner), so this drives the Responses API's tool-calling
loop by hand: call the model, execute any requested function calls, feed
the results back as "function_call_output" items, and repeat until it
answers with plain text instead of more calls.

Stateless on OpenAI's side (`store=False`, so account data isn't kept
there): each call resends the whole turn, including the model's reasoning
items, which come back encrypted (`reasoning.encrypted_content`) so its
thinking carries across tool steps.
"""

import json
import logging
import logging.handlers
import os
from pathlib import Path

from openai import OpenAI

from copilot.rules import trading_rules
from copilot.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# Dedicated logger for per-turn skills/tools usage, written to its own file
# (logs/copilot.log) rather than the general api.log — usage tracking is a
# distinct concern from operational error logging, and this logger doesn't
# propagate to root so entries aren't duplicated into api.log.
_usage_logger = logging.getLogger("copilot.usage")
_usage_logger.setLevel(logging.INFO)
_usage_logger.propagate = False
if not _usage_logger.handlers:
    _log_dir = Path(__file__).resolve().parent.parent / "logs"
    _log_dir.mkdir(exist_ok=True)
    _handler = logging.handlers.RotatingFileHandler(
        _log_dir / "copilot.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _usage_logger.addHandler(_handler)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-6.1-terra")
REASONING_EFFORT = "low"
MAX_TOOL_ITERATIONS = 8  # hard cap so a confused loop can't run away

# The Responses API defaults function tools to strict schemas (every property
# required, no extras), which these hand-written schemas aren't written for.
_TOOLS = [{**schema, "strict": False} for schema in TOOL_SCHEMAS]

_APP_PROMPT = """You are a financial copilot embedded in the user's own options-wheel \
trading app. You have read-only access to their real Schwab brokerage account (positions, \
balances, transaction history) and to live market data (quotes, option chains, price history) \
via Schwab and Tastytrade — always call the appropriate tool to look up real numbers rather \
than estimating or guessing them.

Your responses are rendered as markdown (GitHub-flavored, tables included). When a tool \
returns a list of items with the same shape — positions, trade history, chain rows, price \
candles — present it as a markdown table rather than prose or a bulleted list. Use bold, \
headers, and lists elsewhere where they aid scanability, but don't force a table onto a single \
value or a short narrative answer.

Whenever you give a specific, actionable strike/expiration recommendation (not a purely \
educational or hypothetical answer), also call propose_legs with the concrete leg(s) — this \
lets the app offer an "Apply to StrikeLab" button so the user doesn't have to re-enter what you \
just recommended by hand. Call it in addition to your normal written explanation, never instead \
of it, and only with real strikes/prices pulled from a tool in this same turn, not invented \
numbers. If the current page context includes a StrikeLab selectedExpirationDte, use that \
expiration for the recommendation rather than picking or asking about a different one. For a \
build_strategy candidate: side SELL for negative qty and BUY for positive, quantity = |qty|, \
premium = mid, and dte/expirationDate from the result.

"""


def _build_system_prompt() -> str:
    # The trading rules (copilot/rules.py) are shared with the MCP server
    # Claude Code uses; they end with the strategy-doc catalog.
    return _APP_PROMPT + trading_rules()


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from env
    return _client


def _format_page_context(page_context: dict) -> str:
    page = page_context.get("page", "a page")
    data = page_context.get("data", {})
    return (
        f"\n\n# Current page context\n"
        f"The user is currently looking at {page} in the app, with this state:\n"
        f"```json\n{json.dumps(data, indent=2, default=str)}\n```\n"
        f"Use this to answer questions about \"this position\"/\"what I'm looking at\" "
        f"without asking the user to restate it. It's a snapshot from the moment this "
        f"message was sent, not live — still call a tool for anything not included here "
        f"(e.g. a fresh quote) rather than assuming this stays current."
    )


def chat(messages: list[dict], page_context: dict | None = None) -> dict:
    """Run one turn of the copilot agent against the given conversation
    history (list of {"role": "user"|"assistant", "content": str}).

    page_context, when given, is {"page": str, "data": dict} describing
    whatever the user is currently looking at (e.g. StrikeLab's in-progress
    position — see frontend/src/utils/copilotContext.js) — folded into this
    turn's system prompt so the agent can answer questions about it directly.

    Returns {"reply": str, "tools_used": [str, ...], "proposed_legs": [dict, ...] | None}.
    proposed_legs is populated when the model called the propose_legs tool
    this turn (see copilot/tools.py) — the frontend renders it as an "Apply
    to StrikeLab" button rather than making the user re-enter what was just
    recommended by hand.
    """
    system_prompt = _build_system_prompt()
    if page_context:
        system_prompt += _format_page_context(page_context)
    conversation = list(messages)
    tools_used: list[str] = []
    proposed_legs: list[dict] | None = None
    _usage_logger.info("Copilot turn started")

    for _ in range(MAX_TOOL_ITERATIONS):
        response = _get_client().responses.create(
            model=MODEL,
            instructions=system_prompt,
            input=conversation,
            tools=_TOOLS,
            reasoning={"effort": REASONING_EFFORT},
            store=False,
            include=["reasoning.encrypted_content"],
        )
        conversation += response.output
        calls = [item for item in response.output if item.type == "function_call"]

        if not calls:
            _usage_logger.info("Copilot turn finished; tools used: %s", tools_used)
            return {"reply": response.output_text, "tools_used": tools_used, "proposed_legs": proposed_legs}

        for call in calls:
            name = call.name
            tools_used.append(name)
            fn = TOOL_FUNCTIONS.get(name)
            if fn is None:
                result = json.dumps({"error": f"Unknown tool {name!r}"})
            else:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                # propose_legs carries no broker call and nothing the model
                # needs back beyond a plain ack (still executed via
                # TOOL_FUNCTIONS below, for that ack) — its real effect is
                # surfacing the legs here, in the turn's own return value,
                # for the frontend to offer as an "Apply to StrikeLab" button.
                if name == "propose_legs":
                    proposed_legs = args.get("legs")
                elif name == "read_strategy_docs":
                    _usage_logger.info("Copilot read strategy docs: %s", args.get("names"))
                try:
                    result = fn(**args)
                except TypeError as e:
                    # A malformed/unexpected argument set — report it back to
                    # the model as a tool error rather than letting the whole
                    # request 500.
                    logger.error("Copilot tool %s called with bad args %r: %s", name, args, e)
                    result = json.dumps({"error": f"Invalid arguments for {name}: {e}"})
            conversation.append(
                {"type": "function_call_output", "call_id": call.call_id, "output": result}
            )

    _usage_logger.info("Copilot turn hit MAX_TOOL_ITERATIONS; tools used: %s", tools_used)
    return {
        "reply": "I wasn't able to finish that within the allowed number of steps — "
        "try rephrasing or narrowing the question.",
        "tools_used": tools_used,
        "proposed_legs": proposed_legs,
    }
