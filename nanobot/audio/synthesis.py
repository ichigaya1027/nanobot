"""Synthesize complete WAV audio through Bailian's HTTP API."""

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from nanobot.audio.synthesis_config import SpeechSynthesisConfig
from nanobot.config.loader import resolve_env_refs


class SpeechSynthesisError(RuntimeError):
    """Speech synthesis or its audio download failed before QQ delivery."""


@dataclass(frozen=True)
class SynthesizedSpeech:
    audio: bytes
    request_id: str


class _Audio(BaseModel):
    url: str


class _Output(BaseModel):
    audio: _Audio


class _SynthesisResponse(BaseModel):
    request_id: str
    output: _Output


async def synthesize_speech(
    text: str,
    config: SpeechSynthesisConfig,
    *,
    instruction: str | None = None,
) -> SynthesizedSpeech:
    api_base = resolve_env_refs(config.api_base)
    api_key = resolve_env_refs(config.api_key)
    if not api_base or not api_key:
        raise SpeechSynthesisError("Speech synthesis endpoint and API key must be configured")
    inputs: dict[str, str | int] = {
        "text": text, "voice": config.voice, "format": "wav", "sample_rate": 24000,
    }
    if instruction is not None:
        inputs["instruction"] = instruction
    stage = "synthesis"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                api_base.rstrip("/") + "/services/audio/tts/SpeechSynthesizer",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": config.model, "input": inputs},
            )
            response.raise_for_status()
            result = _SynthesisResponse.model_validate_json(response.content)
            stage = "download"
            audio = await client.get(result.output.audio.url)
            audio.raise_for_status()
    except httpx.HTTPError as error:
        detail = f"HTTP {error.response.status_code}" if isinstance(error, httpx.HTTPStatusError) else type(error).__name__
        raise SpeechSynthesisError(f"Speech {stage} failed ({detail})") from error
    except ValidationError as error:
        raise SpeechSynthesisError("Invalid speech synthesis response") from error
    if not audio.content:
        raise SpeechSynthesisError("Speech download returned no audio")
    return SynthesizedSpeech(audio.content, result.request_id)
