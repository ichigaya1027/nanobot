"""Bailian speech synthesis through its documented HTTP boundary."""

import json

import httpx
import pytest
from pydantic import ValidationError

from nanobot.audio.synthesis import SpeechSynthesisError, synthesize_speech
from nanobot.config.schema import Config


def configured_speech():
    return Config.model_validate({"speechSynthesis": {
        "enabled": True,
        "apiBase": "https://workspace.test/api/v1",
        "apiKey": "test-tts-key",
        "voice": "custom-paimon-voice",
    }}).speech_synthesis


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


@pytest.mark.parametrize("missing", ["apiBase", "apiKey", "voice"])
def test_enabled_synthesis_requires_connection_and_voice_configuration(missing):
    values = {"enabled": True, "apiBase": "https://workspace.test/api/v1",
              "apiKey": "test-tts-key", "voice": "custom-paimon-voice"}
    del values[missing]
    with pytest.raises(ValidationError):
        Config.model_validate({"speechSynthesis": values})


def test_synthesis_is_opt_in_and_config_uses_camel_case():
    assert not Config().speech_synthesis.enabled
    saved = Config.model_validate({"speechSynthesis": {
        "enabled": True, "apiBase": "https://workspace.test/api/v1",
        "apiKey": "test-tts-key", "voice": "custom-paimon-voice",
    }}).model_dump(by_alias=True)
    assert saved["speechSynthesis"]["voice"] == "custom-paimon-voice"


@pytest.mark.asyncio
@pytest.mark.parametrize("instruction", [None, "Speak cheerfully"])
async def test_synthesis_downloads_wav_with_selected_voice(monkeypatch, instruction):
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={
                "request_id": "tts-request-42",
                "output": {"audio": {"url": "https://audio.test/voice.wav?signature=example"}},
            })
        return httpx.Response(200, content=b"complete WAV audio")

    mock_http(monkeypatch, respond)
    result = await synthesize_speech("Hello traveler", configured_speech(), instruction=instruction)
    assert result.audio == b"complete WAV audio"
    assert result.request_id == "tts-request-42"
    assert str(requests[0].url) == "https://workspace.test/api/v1/services/audio/tts/SpeechSynthesizer"
    assert requests[0].headers["authorization"] == "Bearer test-tts-key"
    expected = {"text": "Hello traveler", "voice": "custom-paimon-voice",
                "format": "wav", "sample_rate": 24000}
    if instruction is not None:
        expected["instruction"] = instruction
    assert json.loads(requests[0].content) == {"model": "qwen-audio-3.1-tts-plus", "input": expected}
    assert str(requests[1].url) == "https://audio.test/voice.wav?signature=example"
    assert "authorization" not in requests[1].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["synthesis", "download"])
async def test_synthesis_reports_http_failure_at_the_failed_stage(monkeypatch, failure):
    def respond(request):
        if request.method == "POST":
            if failure == "synthesis":
                return httpx.Response(503)
            return httpx.Response(200, json={
                "request_id": "tts-request-42",
                "output": {"audio": {"url": "https://audio.test/voice.wav"}},
            })
        return httpx.Response(502)

    mock_http(monkeypatch, respond)
    with pytest.raises(SpeechSynthesisError, match=failure):
        await synthesize_speech("Hello traveler", configured_speech())
