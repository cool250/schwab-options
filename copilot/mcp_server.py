"""The copilot's read-only tools as a local MCP server, for Claude Code.

Same tools (copilot/tools.py) and trading rules (copilot/rules.py, sent as
the server's instructions) as the in-app copilot, so trading questions get
the same answers from either. Runs on your machine over stdio — `.mcp.json`
at the repo root registers it, so Claude Code starts it in this project:

    uv run python -m copilot.mcp_server [--user NAME]

Account data is one user's, as in the app: their Schwab token, broker and
chosen account. Default is the bootstrap admin (user 1); --user picks
another admin. propose_legs is left out — it only feeds the app's Apply
Trade button. The `mcp` package is a dev dependency, so it isn't in the
production image.
"""

import argparse
import json
import sys

import anyio
import anyio.to_thread
from dotenv import load_dotenv

load_dotenv()

import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from api import users  # noqa: E402
from broker.request_context import set_selected_account, set_selected_broker  # noqa: E402
from broker.schwab.auth.token_provider import require_token_owner, set_token_owner  # noqa: E402
from copilot.rules import trading_rules  # noqa: E402
from copilot.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS  # noqa: E402

APP_ONLY_TOOLS = {"propose_legs"}

INSTRUCTIONS = (
    "These tools read the user's real Schwab account (positions, balances, transaction "
    "history) and live Tastytrade market data (quotes, option chains, price history), "
    "read-only. Use them for the user's trading questions instead of estimating numbers, "
    "and follow these rules, the same ones the app's copilot follows:\n\n" + trading_rules()
)

TOOLS = [
    types.Tool(name=s["name"], description=s["description"], input_schema=s["parameters"])
    for s in TOOL_SCHEMAS
    if s["name"] not in APP_ONLY_TOOLS
]


def account_user(username: str | None) -> users.User:
    users.init_db()
    user = users.get_user_by_username(username) if username else users.get_user(1)
    if user is None or user.disabled:
        sys.exit(f"No enabled user {username or 'with id 1'}")
    if not user.is_admin:
        sys.exit(f"{user.username} isn't an admin; the copilot is admin-only")
    return user


def call_tool(user: users.User, name: str, arguments: dict) -> str:
    """Run one tool as `user`. The broker context is set per call, as
    require_auth does per request, since a ContextVar set elsewhere may not
    reach the task handling this call. The user is re-read each time, so a
    broker or account switched in the app applies without a restart."""
    if name in APP_ONLY_TOOLS or name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool {name!r}"})
    user = users.get_user(user.id) or user
    set_token_owner(user.id)
    set_selected_broker(user.broker)
    set_selected_account(user.broker_account)
    try:
        return TOOL_FUNCTIONS[name](**arguments)
    except TypeError as e:
        return json.dumps({"error": f"Invalid arguments for {name}: {e}"})


async def run_tool(user: users.User, name: str, arguments: dict) -> str:
    """call_tool in a worker thread: the Tastytrade client's live quotes
    start their own event loop (asyncio.run), which can't run inside the
    server's — FastAPI runs the app's sync routes in a thread pool the same
    way. call_tool sets the user's broker context itself, inside the thread."""
    return await anyio.to_thread.run_sync(call_tool, user, name, arguments)


def build_server(user: users.User) -> Server:
    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def handle_call(ctx, params) -> types.CallToolResult:
        result = await run_tool(user, params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=result)])

    return Server(
        "options-wheel",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=handle_call,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", help="admin whose account the tools read (default: user 1)")
    user = account_user(parser.parse_args().user)
    # As in the web app: a Schwab call with no owner raises rather than
    # falling back to the bootstrap admin's token.
    require_token_owner()
    server = build_server(user)

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
