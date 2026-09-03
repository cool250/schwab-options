"""The copilot agent: system prompt assembly + the OpenAI tool-calling loop.

The core `openai` package has no built-in agentic-loop helper (unlike
Anthropic's Tool Runner), so this drives the standard chat-completions
tool-calling loop by hand: call the model, execute any requested tool
calls, feed the results back as "tool" messages, and repeat until it
answers with plain text instead of more tool calls.
"""

import json
import logging
import os
from pathlib import Path

from openai import OpenAI

from copilot.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_TOOL_ITERATIONS = 8  # hard cap so a confused loop can't run away

_SKILLS_DIR = Path(__file__).parent / "skills"

_BASE_SYSTEM_PROMPT = """You are a financial copilot embedded in the user's own options-wheel \
trading app. You have read-only access to their real Schwab brokerage account (positions, \
balances, transaction history) and to live market data (quotes, option chains, price history) \
via Schwab and Tastytrade — always call the appropriate tool to look up real numbers rather \
than estimating or guessing them.

You are strictly read-only. You cannot place, modify, or cancel any trade, and no tool \
available to you can either — if asked to execute a trade, say plainly that you don't have \
that capability and can only help analyze and explain.

You are knowledgeable about options strategies via the reference material below. When \
discussing a strategy or suggesting one, keep in mind this is not licensed financial advice — \
a brief, natural acknowledgment of that is appropriate when giving specific suggestions, but \
don't repeat a disclaimer on every message.

# Options strategy reference
"""


def _load_skill_docs() -> str:
    """Concatenate every skill markdown file into one reference block. Full
    inclusion rather than retrieval — the doc set is small enough (a handful
    of short strategy write-ups) that RAG/embeddings would be pure overhead
    for a single-user app."""
    docs = []
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        docs.append(path.read_text())
    return "\n\n---\n\n".join(docs)


def _build_system_prompt() -> str:
    return _BASE_SYSTEM_PROMPT + "\n\n" + _load_skill_docs()


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from env
    return _client


def chat(messages: list[dict]) -> dict:
    """Run one turn of the copilot agent against the given conversation
    history (list of {"role": "user"|"assistant", "content": str}).

    Returns {"reply": str, "tools_used": [str, ...]}.
    """
    conversation = [{"role": "system", "content": _build_system_prompt()}] + list(messages)
    tools_used: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = _get_client().chat.completions.create(
            model=MODEL,
            messages=conversation,
            tools=TOOL_SCHEMAS,
            # Reasoning-tier models (e.g. gpt-5.6-terra) reject function
            # tools on /v1/chat/completions unless reasoning is turned off —
            # the alternative is the separate /v1/responses API, which has a
            # different request/response shape this loop isn't built for.
            reasoning_effort="none",
        )
        message = response.choices[0].message
        conversation.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            return {"reply": message.content or "", "tools_used": tools_used}

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            tools_used.append(name)
            fn = TOOL_FUNCTIONS.get(name)
            if fn is None:
                result = json.dumps({"error": f"Unknown tool {name!r}"})
            else:
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = fn(**args)
                except TypeError as e:
                    # A malformed/unexpected argument set — report it back to
                    # the model as a tool error rather than letting the whole
                    # request 500.
                    logger.error("Copilot tool %s called with bad args %r: %s", name, args, e)
                    result = json.dumps({"error": f"Invalid arguments for {name}: {e}"})
            conversation.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result}
            )

    return {
        "reply": "I wasn't able to finish that within the allowed number of steps — "
        "try rephrasing or narrowing the question.",
        "tools_used": tools_used,
    }
