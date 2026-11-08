"""The copilot's Responses API loop (copilot/agent.py), through a stand-in
OpenAI client — no network, no API key."""

import json
from types import SimpleNamespace

import pytest

from copilot import agent, tools


def _call(name, arguments, call_id):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(arguments), call_id=call_id)


def _reasoning():
    return SimpleNamespace(type="reasoning", encrypted_content="opaque")


def _reply(text):
    return SimpleNamespace(output=[_reasoning(), SimpleNamespace(type="message")], output_text=text)


class _Responses:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **kwargs):
        # A copy: the agent keeps appending to the same input list.
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        return self.replies.pop(0)


@pytest.fixture
def responses(monkeypatch):
    def install(*replies):
        stand_in = _Responses(replies)
        monkeypatch.setattr(agent, "_get_client", lambda: SimpleNamespace(responses=stand_in))
        return stand_in
    return install


def test_runs_tools_and_feeds_results_back_with_the_reasoning(responses, monkeypatch):
    monkeypatch.setitem(agent.TOOL_FUNCTIONS, "get_stock_positions", lambda: '{"rows": []}')
    stand_in = responses(
        SimpleNamespace(output=[_reasoning(), _call("get_stock_positions", {}, "c1")], output_text=""),
        _reply("You hold no stock."),
    )

    result = agent.chat([{"role": "user", "content": "What stock do I hold?"}])

    assert result == {"reply": "You hold no stock.", "tools_used": ["get_stock_positions"], "proposed_legs": None}
    first, second = stand_in.requests
    assert first["reasoning"] == {"effort": agent.REASONING_EFFORT}
    assert first["store"] is False
    assert first["include"] == ["reasoning.encrypted_content"]
    assert first["instructions"].startswith("You are a financial copilot")
    assert first["input"] == [{"role": "user", "content": "What stock do I hold?"}]
    # The second call carries the first's reasoning and call, then the tool's output.
    assert [getattr(i, "type", None) for i in second["input"][1:3]] == ["reasoning", "function_call"]
    assert second["input"][3] == {"type": "function_call_output", "call_id": "c1", "output": '{"rows": []}'}


def test_tools_are_flat_and_not_strict():
    assert agent._TOOLS
    for tool in agent._TOOLS:
        assert tool["type"] == "function" and tool["strict"] is False
        assert "function" not in tool and tool["name"] in agent.TOOL_FUNCTIONS


def test_propose_legs_is_returned_for_the_apply_button(responses):
    legs = [{"symbol": "SPY", "side": "SELL", "optionType": "PUT", "strike": 500, "quantity": 1}]
    responses(
        SimpleNamespace(output=[_call("propose_legs", {"legs": legs}, "c1")], output_text=""),
        _reply("Sell the 500 put."),
    )

    result = agent.chat([{"role": "user", "content": "Sell a put on SPY"}])

    assert result["proposed_legs"] == legs
    assert result["tools_used"] == ["propose_legs"]


def test_bad_arguments_and_unknown_tools_go_back_to_the_model_as_errors(responses):
    stand_in = responses(
        SimpleNamespace(output=[_call("get_stock_positions", {"bogus": 1}, "c1"), _call("nope", {}, "c2")], output_text=""),
        _reply("Sorry."),
    )

    agent.chat([{"role": "user", "content": "hi"}])

    outputs = [i for i in stand_in.requests[1]["input"] if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert [o["call_id"] for o in outputs] == ["c1", "c2"]
    assert "Invalid arguments" in json.loads(outputs[0]["output"])["error"]
    assert "Unknown tool" in json.loads(outputs[1]["output"])["error"]


def test_strategy_docs_are_listed_not_loaded():
    instructions = agent._build_system_prompt()
    assert "- iron_condor: Iron Condor" in instructions
    # Only the titles: a doc's body isn't in the prompt.
    body = tools.STRATEGY_DOCS["iron_condor"].read_text().split("\n", 2)[2][:200]
    assert body not in instructions


def test_read_strategy_docs_returns_the_named_docs():
    text = tools.read_strategy_docs(["iron_condor", "naked_put"])
    assert text.startswith("# Iron Condor") and "# Naked Put" in text
    assert "Unknown strategy docs ['nope']" in json.loads(tools.read_strategy_docs(["nope"]))["error"]
    schema = next(t for t in tools.TOOL_SCHEMAS if t["name"] == "read_strategy_docs")
    assert schema["parameters"]["properties"]["names"]["items"]["enum"] == list(tools.STRATEGY_DOCS)


def test_page_context_goes_into_the_instructions(responses):
    stand_in = responses(_reply("ok"))

    agent.chat([{"role": "user", "content": "this?"}], page_context={"page": "StrikeLab", "data": {"spot": 101}})

    assert "# Current page context" in stand_in.requests[0]["instructions"]
    assert '"spot": 101' in stand_in.requests[0]["instructions"]
