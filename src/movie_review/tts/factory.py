"""TTS adapter selection from a model spec."""

from __future__ import annotations

from movie_review.config.settings import ModelSpec, require_cloud_ai
from movie_review.tts.openai_compat import OpenAICompatTTSAdapter
from movie_review.tts.port import TTSPort
from movie_review.tts.qwen_tts import QwenTTSAdapter


def build_tts_adapter(spec: ModelSpec) -> TTSPort:
    """Build the narration adapter described by ``spec``.

    ``pcm_sample_rate`` only matters when the remote server is asked for
    headerless PCM; WAV responses describe themselves.
    """
    if not spec.enabled:
        raise ValueError(f"TTS model {spec.model!r} is disabled")
    require_cloud_ai(spec, spec.cloud_ai, "tts")
    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatTTSAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
        )
    return QwenTTSAdapter(spec.model)
