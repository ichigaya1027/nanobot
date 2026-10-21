"""Group scope is independent of private-chat user authorization."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.delivery import DeliveryRejectedError
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.napcat.runtime import NapcatChannel
from nanobot.channels.napcat.tests.test_group_agent import message
from nanobot.providers.base import GenerationSettings, LLMResponse


@pytest.fixture
def pairing(monkeypatch):
    monkeypatch.setattr("nanobot.channels.base.is_approved", lambda channel, user: user == "9")


@pytest.mark.asyncio
@pytest.mark.parametrize("autonomous", [False, True])
async def test_allowed_group_accepts_member_outside_private_allowlist(autonomous, pairing):
    channel = NapcatChannel({
        "allowFrom": ["7"], "allowGroups": ["100"], "groupPolicy": "open",
        "groupAgent": {"enabled": autonomous, "groups": ["100"], "batchSeconds": 0.01},
    }, MessageBus())
    try:
        await channel._on_message(message(user=8))
        received = await asyncio.wait_for(channel.bus.consume_inbound(), 1)
        assert received.chat_id == "group:100"
        assert "hello" in received.content
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("user,allow_from", [(7, ["7"]), (9, []), (8, ["*"])])
@pytest.mark.parametrize("autonomous", [False, True])
async def test_other_group_is_rejected_before_media_or_background_queries(user, allow_from, autonomous, pairing):
    channel = NapcatChannel({
        "allowFrom": allow_from, "allowGroups": ["100"], "groupPolicy": "open",
        "groupAgent": {"enabled": autonomous, "groups": ["200"], "batchSeconds": 0.01, "directedBatchSeconds": 0.01},
    }, MessageBus())
    channel._self_id = 42
    channel._download_image = AsyncMock(return_value="image.png")
    channel._call_action = AsyncMock(return_value={"data": {}})
    try:
        await channel._on_message(message(user=user, group_id=200, message=[
            {"type": "at", "data": {"qq": "42"}},
            {"type": "reply", "data": {"id": "88"}},
            {"type": "image", "data": {"url": "https://example.com/image.png"}},
        ]))
        await asyncio.sleep(0.05)
        assert channel.bus.inbound_size == 0
        channel._download_image.assert_not_awaited()
        channel._call_action.assert_not_awaited()
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("group_config", [{}, {"allowGroups": []}])
async def test_missing_or_empty_group_allowlist_accepts_no_groups(group_config):
    channel = NapcatChannel({"allowFrom": ["*"], "groupPolicy": "open", **group_config}, MessageBus())
    await channel._on_message(message())
    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_from,user,allowed", [
    (["7"], 7, True), (["7"], 8, False), (["*"], 8, True),
    ([], 9, True), ([], 8, False), (["7"], 9, True),
])
async def test_private_chat_preserves_user_and_pairing_authorization(allow_from, user, allowed, pairing):
    channel = NapcatChannel({"allowFrom": allow_from}, MessageBus())
    await channel._on_message({"message_type": "private", "user_id": user, "message": "hello"})
    assert channel.bus.inbound_size == int(allowed)
    if allowed:
        received = await channel.bus.consume_inbound()
        assert received.chat_id == f"private:{user}"
        assert received.sender_id == str(user)


@pytest.mark.asyncio
async def test_member_welcome_uses_group_scope_instead_of_private_allowlist():
    channel = NapcatChannel({"allowFrom": ["7"], "allowGroups": ["100"]}, MessageBus())
    channel._call_action = AsyncMock(return_value={"data": {"nickname": "New member"}})
    await channel._on_notice({"notice_type": "group_increase", "group_id": 100, "user_id": 8})
    received = await asyncio.wait_for(channel.bus.consume_inbound(), 1)
    assert received.chat_id == "group:100"
    assert "New member" in received.content


@pytest.mark.asyncio
@pytest.mark.parametrize("notice", [
    {"notice_type": "group_increase"},
    {"notice_type": "notify", "sub_type": "poke", "target_id": 42},
])
async def test_other_group_notifications_do_not_query_or_publish(notice):
    channel = NapcatChannel({
        "allowFrom": ["*"], "allowGroups": ["100"],
        "groupAgent": {"enabled": True, "groups": ["200"], "directedBatchSeconds": 0.01},
    }, MessageBus())
    channel._self_id = 42
    channel._call_action = AsyncMock(return_value={"data": {}})
    try:
        await channel._on_notice({**notice, "group_id": 200, "user_id": 7})
        await asyncio.sleep(0.05)
        assert channel.bus.inbound_size == 0
        channel._call_action.assert_not_awaited()
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_group_delivery_is_rejected_before_connection_and_media_processing():
    channel = NapcatChannel({"allowGroups": ["100"]}, MessageBus())
    channel._build_image_segment = AsyncMock()
    channel._call_action = AsyncMock()
    with pytest.raises(DeliveryRejectedError):
        await channel.send(OutboundMessage("napcat", "group:200", "hello", media=["image.png"]))
    channel._build_image_segment.assert_not_awaited()
    channel._call_action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["group:100", "private:8"])
async def test_allowed_group_and_unlisted_private_destination_can_send(destination):
    channel = NapcatChannel({"allowGroups": ["100"], "allowFrom": ["7"]}, MessageBus())
    channel._ws = AsyncMock()
    channel._call_action = AsyncMock(return_value={"data": {"message_id": 88}})
    try:
        await channel.send(OutboundMessage("napcat", destination, "hello"))
        channel._call_action.assert_awaited_once()
        params = channel._call_action.call_args.args[1]
        assert params["message"] == [{"type": "text", "data": {"text": "hello"}}]
        assert params.get("group_id", params.get("user_id")) == int(destination.split(":")[1])
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["napcat", "system"])
async def test_existing_group_session_is_rejected_before_model_request(tmp_path, source):
    channel = NapcatChannel({"allowGroups": ["100"]}, MessageBus())
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (1000, "test")
    provider.aclose = AsyncMock()
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="answer"))
    loop = AgentLoop(bus=channel.bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.turn_policy_provider = channel.turn_policy
    try:
        await loop.sessions.state.get("napcat:group:200")
        with pytest.raises(PermissionError):
            await loop._process_message(InboundMessage(
                source, "7" if source == "napcat" else "cron", "group:200" if source == "napcat" else "napcat:group:200",
                "hello", session_key_override="napcat:group:200",
            ))
        provider.chat_stream_with_retry.assert_not_awaited()
    finally:
        await loop.aclose()
        await loop.sessions.state.aclose()
