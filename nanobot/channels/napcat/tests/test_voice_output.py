"""Native QQ voice actions, including the application synthesis path."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.channels.napcat.group_agent import OBSERVATION_KEY, GroupMessage
from nanobot.channels.napcat.group_tools import ActionRejectedError
from nanobot.channels.napcat.tests.test_group_agent import channel, message
from nanobot.config.loader import get_config_path, set_config_path
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest


@pytest.fixture
def voice_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"speechSynthesis": {
        "enabled": True, "apiBase": "https://workspace.test/api/v1",
        "apiKey": "test-tts-key", "voice": "custom-paimon-voice",
    }}), encoding="utf-8")
    previous = get_config_path()
    set_config_path(path)
    try:
        yield path
    finally:
        set_config_path(previous)


@pytest.fixture
def speech_http(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={
                "request_id": "tts-request-42",
                "output": {"audio": {"url": "https://audio.test/voice.wav"}},
            })
        return httpx.Response(200, content=b"complete WAV audio")

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    return requests


def group_input():
    return InboundMessage("napcat", "7", "group:100", "hello", metadata={
        OBSERVATION_KEY: [GroupMessage.parse(message()).wire()],
    })


def test_voice_action_is_absent_when_synthesis_is_disabled(voice_config):
    voice_config.write_text('{"speechSynthesis":{"enabled":false}}', encoding="utf-8")
    ch = channel()
    policy = ch.turn_policy(group_input(), "napcat:group:100", ToolRegistry())
    assert policy is not None
    assert "send_voice" not in policy.tools.tool_names


@pytest.mark.asyncio
async def test_voice_action_sends_native_record_and_returns_receipt(voice_config, speech_http):
    ch = channel()
    ch._call_action = AsyncMock(return_value={"data": {"message_id": 88}})
    policy = ch.turn_policy(group_input(), "napcat:group:100", ToolRegistry())
    assert policy is not None
    try:
        result = await policy.tools.execute("send_voice", {
            "text": "Hello traveler", "instruction": "Speak cheerfully",
        })
        assert json.loads(result) == {"status": "succeeded", "message_id": "88"}
        assert not result.continue_response
        action, params = ch._call_action.await_args.args
        assert action == "send_msg"
        assert params["message_type"] == "group" and params["group_id"] == "100"
        assert len(params["message"]) == 1
        segment = params["message"][0]
        assert segment["type"] == "record"
        assert base64.b64decode(segment["data"]["file"].removeprefix("base64://")) == b"complete WAV audio"
        await ch._on_message(message(88, user=42, post_type="message_sent", message=[segment]))
        await ch._on_message(message(2))
        await ch.group_observer.flush("100")
        batch = await ch.bus.consume_inbound()
        assert "#88" not in batch.content
        assert "#2" in batch.content
    finally:
        await ch.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [
    (ActionRejectedError("transcode rejected"), "failed"),
    (TimeoutError("acknowledgement lost"), "unknown"),
    ({"data": {}}, "unknown"),
])
async def test_unsuccessful_voice_delivery_is_not_a_successful_end(voice_config, speech_http, failure, status):
    ch = channel()
    ch._call_action = AsyncMock(**(
        {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
    ))
    policy = ch.turn_policy(group_input(), "napcat:group:100", ToolRegistry())
    assert policy is not None
    try:
        result = await policy.tools.execute("send_voice", {"text": "Hello traveler"})
        assert result.is_error
        assert result.continue_response
        assert json.JSONDecoder().raw_decode(result)[0]["status"] == status
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_synthesis_failure_does_not_submit_a_qq_send(voice_config, monkeypatch):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503)), **kwargs,
    ))
    ch = channel()
    ch._call_action = AsyncMock()
    policy = ch.turn_policy(group_input(), "napcat:group:100", ToolRegistry())
    assert policy is not None
    try:
        result = await policy.tools.execute("send_voice", {"text": "Hello traveler"})
        assert result.is_error and result.continue_response
        assert json.JSONDecoder().raw_decode(result)[0]["status"] == "failed"
        ch._call_action.assert_not_awaited()
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_voice_reply_finishes_without_another_model_request(voice_config, speech_http, tmp_path):
    ch = channel()
    ch._call_action = AsyncMock(return_value={"data": {"message_id": 88}})
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (1000, "test")
    provider.aclose = AsyncMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="voice", name="send_voice", arguments={
                "text": "Hello traveler",
            }),
        ]),
        LLMResponse(content="unexpected extra model request"),
    ])
    loop = AgentLoop(bus=ch.bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.turn_policy_provider = ch.turn_policy
    try:
        assert await loop._process_message(group_input()) is None
        assert provider.chat_stream_with_retry.await_count == 1
        assert ch._call_action.await_count == 1
    finally:
        await ch.stop()
        await loop.aclose()
        await loop.sessions.state.aclose()
