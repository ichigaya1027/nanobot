"""Configuration for the selected Bailian speech synthesis API."""

from typing import Self

from pydantic import Field, model_validator

from nanobot.config_base import Base


class SpeechSynthesisConfig(Base):
    enabled: bool = False
    api_base: str = ""
    api_key: str = Field(default="", repr=False)
    model: str = "qwen-audio-3.1-tts-plus"
    voice: str = ""

    @model_validator(mode="after")
    def _require_enabled_configuration(self) -> Self:
        if self.enabled:
            missing = [name for name in ("api_base", "api_key", "model", "voice") if not getattr(self, name).strip()]
            if missing:
                raise ValueError("Enabled speech synthesis requires: " + ", ".join(missing))
        return self
