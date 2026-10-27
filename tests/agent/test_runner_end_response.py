"""A successful complete tool group can finish without a model round trip."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMResponse, ToolCallRequest


class Action(Tool):
    def __init__(self, name, result, executed):
        self._name, self.result, self.executed = name, result, executed

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return "Perform a test action"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        self.executed.append(self.name)
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_finish_requires_every_call_to_succeed_and_preserves_later_calls(failure):
    executed = []
    registry = ToolRegistry()
    registry.register(Action("respond", ToolResult("delivered", continue_response=False), executed))
    registry.register(Action("second", ToolResult.error("failed") if failure else ToolResult("done", continue_response=False), executed))
    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="a", name="respond", arguments={}),
            ToolCallRequest(id="b", name="second", arguments={}),
        ]),
        LLMResponse(content="handle failed operation"),
    ])
    checkpoints = []

    async def checkpoint(payload):
        checkpoints.append(payload)

    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "act"}], tools=registry,
        model="test-model", max_iterations=4, max_tool_result_chars=10000,
        checkpoint_callback=checkpoint,
    ))
    assert executed == ["respond", "second"]
    assert provider.chat_stream_with_retry.await_count == (2 if failure else 1)
    assert {m["tool_call_id"] for m in result.messages if m["role"] == "tool"} == {"a", "b"}
    assert any(p["phase"] == "tools_completed" and len(p["completed_tool_results"]) == 2 for p in checkpoints)
    if not failure:
        assert result.final_content is None


@pytest.mark.asyncio
async def test_failed_group_finish_request_does_not_leak_to_next_group():
    registry = ToolRegistry()
    registry.register(Action("finish", ToolResult("ok", continue_response=False), []))
    registry.register(Action("bad", ToolResult.error("failed"), []))
    registry.register(Action("read", ToolResult("data"), []))
    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="a", name="finish", arguments={}),
            ToolCallRequest(id="b", name="bad", arguments={}),
        ]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest(id="c", name="read", arguments={})]),
        LLMResponse(content="finished"),
    ])
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "act"}], tools=registry,
        model="test-model", max_iterations=5, max_tool_result_chars=10000,
    ))
    assert provider.chat_stream_with_retry.await_count == 3
    assert result.final_content == "finished"
