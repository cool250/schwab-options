"""The copilot's MCP server for Claude Code (copilot/mcp_server.py): same
tools and rules as the app's copilot, run as one user — no network."""

import json

from api.users import User
from broker.request_context import get_selected_account, get_selected_broker
from broker.schwab.auth import token_provider
from copilot import mcp_server, tools
from copilot.rules import trading_rules

USER = User(id=7, username="ann", is_admin=True, disabled=False, created_at=0, password_changed_at=0,
            broker="schwab", broker_account="123")


def test_same_tools_as_the_app_except_the_apply_button():
    names = [t.name for t in mcp_server.TOOLS]
    assert names == [s["name"] for s in tools.TOOL_SCHEMAS if s["name"] != "propose_legs"]
    assert mcp_server.INSTRUCTIONS.endswith(trading_rules())


def test_tools_run_as_the_chosen_user(monkeypatch):
    seen = {}

    def fake():
        seen.update(owner=token_provider._token_owner.get(), broker=get_selected_broker(),
                    account=get_selected_account())
        return "{}"

    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "get_account_balances", fake)
    assert mcp_server.call_tool(USER, "get_account_balances", {}) == "{}"
    assert seen == {"owner": 7, "broker": "schwab", "account": "123"}


def test_unknown_tools_and_bad_arguments_are_errors():
    assert "Unknown tool 'propose_legs'" in json.loads(mcp_server.call_tool(USER, "propose_legs", {"legs": []}))["error"]
    assert "Invalid arguments" in json.loads(mcp_server.call_tool(USER, "get_account_balances", {"x": 1}))["error"]
