"""TTS models (spec sections 39-41)."""

from __future__ import annotations

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat, PositiveInt


class TTSRequest(BaseModel):
    """One synthesis request; voice comes from configuration, never code."""

    text: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    emotion: str = "neutral"
    speed: PositiveFloat = 1.0


class SpeechAudio(BaseModel):
    """Synthesized PCM audio with measured duration."""

    duration_seconds: NonNegativeFloat
    sample_rate: PositiveInt
    audio: bytes
