"""Balanced model profile contract (T077, plan section 5).

The balanced profile is the default: Whisper large-v3-turbo for ASR,
Qwen3-VL for vision, Qwen3.5-27B for reasoning, critic disabled, and
Qwen3-TTS 1.7B for narration. This module pins that contract in code so
benchmark-driven checkpoint edits in ``config.yaml`` cannot silently
change the profile shape.
"""

from __future__ import annotations

from movie_review.config.settings import AppSettings

BALANCED_PROFILE = "balanced"

EXPECTED_BALANCED_MODELS = {
    "asr": "whisper-large-v3-turbo",
    "vision": "Qwen3-VL",
    "reasoning": "Qwen3.5-27B",
    "tts": "Qwen3-TTS-12Hz-1.7B",
}

#: Initial performance target (plan NFR-004): measurement goal, not a gate.
BALANCED_TARGET_SECONDS_PER_HOUR = 4 * 3600


class ProfileError(Exception):
    """Balanced profile contract violated."""


def validate_balanced_profile(settings: AppSettings) -> None:
    """Raise :class:`ProfileError` unless the balanced contract holds."""
    if settings.models.profile != BALANCED_PROFILE:
        raise ProfileError(f"Expected profile 'balanced', got {settings.models.profile!r}")
    actual = {
        "asr": settings.models.asr.model,
        "vision": settings.models.vision.model,
        "reasoning": settings.models.reasoning.model,
        "tts": settings.models.tts.model,
    }
    for key, expected in EXPECTED_BALANCED_MODELS.items():
        if actual[key] != expected:
            raise ProfileError(f"Balanced {key}: expected {expected!r}, got {actual[key]!r}")
    if settings.models.critic.enabled:
        raise ProfileError("Balanced profile must keep the critic disabled")
