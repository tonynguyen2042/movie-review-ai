"""Remote ASR / VLM / TTS adapters: multipart upload, images, measured audio."""

import io
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from movie_review.asr import (
    ASRError,
    ASRPort,
    ModelUnavailableError,
    OpenAICompatASRAdapter,
    build_asr_adapter,
)
from movie_review.config.settings import ModelSpec
from movie_review.domain.tts import TTSRequest
from movie_review.tts import (
    OpenAICompatTTSAdapter,
    TTSError,
    TTSPort,
    TTSUnavailableError,
    build_tts_adapter,
)
from movie_review.vision import (
    AnalysisInput,
    OpenAICompatVLMAdapter,
    VLMError,
    VLMPort,
    VLMUnavailableError,
    build_vlm_adapter,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _wav(frames: int = 24000, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * (frames * channels * width))
    return buf.getvalue()


def _transcription_body(segments: list[dict[str, Any]]) -> bytes:
    text = " ".join(s["text"] for s in segments)
    return json.dumps({"text": text, "segments": segments}).encode()


def _audio(tmp_path: Path) -> Path:
    path = tmp_path / "audio.wav"
    path.write_bytes(_wav(frames=100))
    return path


def _frame(tmp_path: Path) -> Path:
    # 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
    )
    path = tmp_path / "frame.png"
    path.write_bytes(png)
    return path


# ==========================================================================
# ASR
# ==========================================================================


def test_asr_adapter_satisfies_port() -> None:
    assert isinstance(OpenAICompatASRAdapter("m", "http://gpu:9000/v1"), ASRPort)


def test_asr_transcribe_uploads_multipart_and_maps_segments(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["content_type"] = dict(request.headers).get("Content-type")
        seen["body"] = request.data
        return FakeResponse(
            _transcription_body(
                [
                    {"start": 0.0, "end": 1.5, "text": "Hello there."},
                    {"start": 1.5, "end": 3.0, "text": "General Kenobi."},
                ]
            )
        )

    adapter = OpenAICompatASRAdapter(
        "whisper-large-v3-turbo", "http://gpu:9000/v1", transport=transport
    )
    segments = adapter.transcribe(_audio(tmp_path), language="en")

    assert seen["url"] == "http://gpu:9000/v1/audio/transcriptions"
    assert "multipart/form-data; boundary=" in seen["content_type"]
    body = seen["body"]
    assert b'name="model"' in body
    assert b"whisper-large-v3-turbo" in body
    assert b'name="response_format"' in body
    assert b"verbose_json" in body
    assert b'name="language"' in body and b"en" in body
    assert b'name="file"; filename="audio.wav"' in body

    assert [s.text for s in segments] == ["Hello there.", "General Kenobi."]
    assert segments[0].start == 0.0
    assert segments[0].end == 1.5


def test_asr_omits_language_when_not_requested(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["body"] = request.data
        return FakeResponse(_transcription_body([{"start": 0, "end": 1, "text": "x"}]))

    OpenAICompatASRAdapter("m", "http://g/v1", transport=transport).transcribe(_audio(tmp_path))
    assert b'name="language"' not in seen["body"]


def test_asr_rejects_missing_audio(tmp_path: Path) -> None:
    adapter = OpenAICompatASRAdapter("m", "http://g/v1", transport=lambda r, t: FakeResponse(b""))
    with pytest.raises(ASRError, match="does not exist"):
        adapter.transcribe(tmp_path / "absent.wav")


def test_asr_rejects_text_only_response(tmp_path: Path) -> None:
    """A server that ignores verbose_json must fail with actionable guidance."""
    adapter = OpenAICompatASRAdapter(
        "m", "http://g/v1", transport=lambda r, t: FakeResponse(b'{"text": "hello"}')
    )
    with pytest.raises(ASRError, match="response_format=verbose_json"):
        adapter.transcribe(_audio(tmp_path))


def test_asr_rejects_empty_segments(tmp_path: Path) -> None:
    adapter = OpenAICompatASRAdapter(
        "m",
        "http://g/v1",
        transport=lambda r, t: FakeResponse(b'{"text": "", "segments": []}'),
    )
    with pytest.raises(ASRError, match="without timestamps"):
        adapter.transcribe(_audio(tmp_path))


def test_asr_unreachable_is_model_unavailable(tmp_path: Path) -> None:
    from urllib.error import URLError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise URLError("refused")

    adapter = OpenAICompatASRAdapter("whisper", "http://g/v1", transport=transport)
    with pytest.raises(ModelUnavailableError):
        adapter.transcribe(_audio(tmp_path))


def test_asr_http_error_classified_without_token(tmp_path: Path) -> None:
    from email.message import Message
    from urllib.error import HTTPError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise HTTPError("http://g", 503, "down", Message(), None)

    adapter = OpenAICompatASRAdapter(
        "whisper", "http://g/v1", api_key="s3cret", transport=transport
    )
    with pytest.raises(ASRError) as exc:
        adapter.transcribe(_audio(tmp_path))
    assert "503" in str(exc.value)
    assert "s3cret" not in str(exc.value)


# ---------------------------------------------------------------------------
# Servers whose ASR route is not the OpenAI one
# ---------------------------------------------------------------------------


def test_asr_route_can_be_overridden(tmp_path: Path) -> None:
    """whisper.cpp serves POST /inference and has no /audio/transcriptions.

    Sending the request to the OpenAI path against a healthy whisper-server
    produces a 404, which reads like the server is down when it is not.
    """
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        return FakeResponse(_transcription_body([{"start": 0.0, "end": 1.0, "text": "Hi."}]))

    adapter = OpenAICompatASRAdapter(
        "ggml-large-v3-turbo-q5_0",
        "http://gpu:9000",
        transport=transport,
        endpoint_path="/inference",
    )
    segments = adapter.transcribe(_audio(tmp_path), language="en")

    assert seen["url"] == "http://gpu:9000/inference"
    assert [s.text for s in segments] == ["Hi."]


def test_asr_route_defaults_to_the_openai_path(tmp_path: Path) -> None:
    """Unset must not change behaviour for faster-whisper-server and friends."""
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        return FakeResponse(_transcription_body([{"start": 0.0, "end": 1.0, "text": "Hi."}]))

    OpenAICompatASRAdapter("m", "http://gpu:9000/v1", transport=transport).transcribe(
        _audio(tmp_path)
    )

    assert seen["url"] == "http://gpu:9000/v1/audio/transcriptions"


def test_adapter_exposes_its_route() -> None:
    assert (
        OpenAICompatASRAdapter("m", "http://gpu:9000", endpoint_path="/inference").endpoint_path
        == "/inference"
    )
    assert OpenAICompatASRAdapter("m", "http://gpu:9000").endpoint_path == "/audio/transcriptions"


def test_whisper_cpp_segments_map_without_translation() -> None:
    """whisper.cpp returns avg_logprob, which map_segments reads for confidence."""
    # Shape captured from a live whisper-server verbose_json response.
    document = {
        "text": " .",
        "segments": [
            {
                "id": 0,
                "text": " .",
                "start": 0.0,
                "end": 1.0,
                "tokens": [2411],
                "temperature": 0.0,
                "avg_logprob": -0.5,
            }
        ],
    }
    adapter = OpenAICompatASRAdapter("m", "http://gpu:9000")
    segments = adapter._segments_from(document, "http://gpu:9000/inference", "en")

    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].end == 1.0
    assert 0.0 < segments[0].confidence <= 1.0


def test_endpoint_path_is_appended_to_base_url(tmp_path: Path) -> None:
    """Documented trap: a /v1 base yields /v1/inference, which 404s on whisper.cpp.

    whisper-server serves /inference at the root, so combining it with a base_url
    that ends in /v1 -- the shape every OpenAI-compatible host uses -- produces a
    404 from a healthy server. Pinning the join makes the requirement for a bare
    host visible instead of something to rediscover against the network.
    """
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        return FakeResponse(_transcription_body([{"start": 0.0, "end": 1.0, "text": "Hi."}]))

    OpenAICompatASRAdapter(
        "m", "http://gpu:9000/v1", transport=transport, endpoint_path="/inference"
    ).transcribe(_audio(tmp_path))

    assert seen["url"] == "http://gpu:9000/v1/inference"


def test_endpoint_path_reaches_the_adapter_from_config() -> None:
    """The value has to travel models.yaml -> ModelSpec -> adapter."""
    spec = ModelSpec(
        model="ggml-large-v3-turbo-q5_0",
        backend="openai_compatible",
        base_url="http://gpu:9000",
        endpoint_path="/inference",
    )
    adapter = build_asr_adapter(spec)
    assert isinstance(adapter, OpenAICompatASRAdapter)
    assert adapter.endpoint_path == "/inference"


def test_endpoint_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="must start with"):
        ModelSpec(
            model="m",
            backend="openai_compatible",
            base_url="http://gpu:9000",
            endpoint_path="inference",
        )


def test_endpoint_path_rejected_for_local_backend() -> None:
    """A route on a backend that never makes HTTP requests is a config error."""
    with pytest.raises(ValueError, match="only applies to backend"):
        ModelSpec(model="m", backend="mlx", endpoint_path="/inference")


def test_asr_requires_base_url() -> None:
    with pytest.raises(ASRError, match="base_url is required"):
        OpenAICompatASRAdapter("m", "")


# ==========================================================================
# VLM
# ==========================================================================


def test_vlm_adapter_satisfies_port() -> None:
    assert isinstance(OpenAICompatVLMAdapter("m", "http://gpu:8000/v1"), VLMPort)


def test_vlm_sends_base64_image_and_parses_analysis(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "location": "Lighthouse",
                                        "characters": ["Marina"],
                                        "importance": 0.8,
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()
        )

    adapter = OpenAICompatVLMAdapter("Qwen3-VL", "http://gpu:8000/v1", transport=transport)
    result = adapter.analyze(
        AnalysisInput(scene_id="scene_000001", frames=[_frame(tmp_path)]),
        "Describe the scene.",
    )

    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "text", "text": "Describe the scene."}

    assert result.scene_id == "scene_000001"
    assert result.location == "Lighthouse"
    assert result.characters == ["Marina"]
    assert result.importance == 0.8


def test_vlm_sends_multiple_frames_in_order(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    a, b = _frame(tmp_path), tmp_path / "frame2.png"
    b.write_bytes(a.read_bytes())
    OpenAICompatVLMAdapter("m", "http://g/v1", transport=transport).analyze(
        AnalysisInput(scene_id="s1", frames=[a, b]), "p"
    )
    images = [p for p in seen["body"]["messages"][0]["content"] if p["type"] == "image_url"]
    assert len(images) == 2


def test_vlm_scene_id_wins_over_model_output(tmp_path: Path) -> None:
    """The model may not rename the scene."""
    adapter = OpenAICompatVLMAdapter(
        "m",
        "http://g/v1",
        transport=lambda r, t: FakeResponse(
            json.dumps({"choices": [{"message": {"content": '{"scene_id": "hijacked"}'}}]}).encode()
        ),
    )
    result = adapter.analyze(AnalysisInput(scene_id="scene_000042", frames=[_frame(tmp_path)]), "p")
    assert result.scene_id == "scene_000042"


def test_vlm_tolerates_fenced_json(tmp_path: Path) -> None:
    adapter = OpenAICompatVLMAdapter(
        "m",
        "http://g/v1",
        transport=lambda r, t: FakeResponse(
            json.dumps(
                {"choices": [{"message": {"content": '```json\n{"location": "Dock"}\n```'}}]}
            ).encode()
        ),
    )
    result = adapter.analyze(AnalysisInput(scene_id="s", frames=[_frame(tmp_path)]), "p")
    assert result.location == "Dock"


def test_vlm_rejects_invalid_analysis(tmp_path: Path) -> None:
    adapter = OpenAICompatVLMAdapter(
        "m",
        "http://g/v1",
        transport=lambda r, t: FakeResponse(
            json.dumps({"choices": [{"message": {"content": '{"importance": 5.0}'}}]}).encode()
        ),
    )
    with pytest.raises(VLMError, match="Invalid scene analysis"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[_frame(tmp_path)]), "p")


def test_vlm_requires_frames(tmp_path: Path) -> None:
    adapter = OpenAICompatVLMAdapter("m", "http://g/v1")
    with pytest.raises(VLMError, match="at least one frame"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[]), "p")


def test_vlm_rejects_missing_frame_file(tmp_path: Path) -> None:
    adapter = OpenAICompatVLMAdapter("m", "http://g/v1")
    with pytest.raises(VLMError, match="not found"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[tmp_path / "no.png"]), "p")


def test_vlm_rejects_empty_prompt(tmp_path: Path) -> None:
    adapter = OpenAICompatVLMAdapter("m", "http://g/v1")
    with pytest.raises(VLMError, match="must not be empty"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[_frame(tmp_path)]), "  ")


def test_vlm_unreachable_is_unavailable(tmp_path: Path) -> None:
    from urllib.error import URLError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise URLError("refused")

    adapter = OpenAICompatVLMAdapter("m", "http://g/v1", transport=transport)
    with pytest.raises(VLMUnavailableError):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[_frame(tmp_path)]), "p")


# ==========================================================================
# TTS
# ==========================================================================


def test_tts_adapter_satisfies_port() -> None:
    assert isinstance(OpenAICompatTTSAdapter("m", "http://gpu:8000/v1"), TTSPort)


def test_tts_duration_measured_from_wav_bytes() -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse(_wav(frames=48000, rate=24000))

    adapter = OpenAICompatTTSAdapter("Qwen3-TTS", "http://gpu:8000/v1", transport=transport)
    audio = adapter.synthesize(TTSRequest(text="Hello.", voice="af"))

    assert seen["url"] == "http://gpu:8000/v1/audio/speech"
    assert seen["body"]["input"] == "Hello."
    assert seen["body"]["voice"] == "af"
    assert seen["body"]["response_format"] == "wav"
    # 48000 frames at 24kHz == 2.0s, derived from the header
    assert audio.sample_rate == 24000
    assert audio.duration_seconds == pytest.approx(2.0)
    assert audio.audio.startswith(b"RIFF")


def test_tts_duration_scales_with_frames() -> None:
    adapter = OpenAICompatTTSAdapter("m", "http://g/v1")
    short = adapter._measure(_wav(frames=12000, rate=24000), "u")
    long = adapter._measure(_wav(frames=48000, rate=24000), "u")
    assert long.duration_seconds == pytest.approx(4 * short.duration_seconds)


def test_tts_pcm_duration_uses_configured_rate() -> None:
    adapter = OpenAICompatTTSAdapter(
        "m", "http://g/v1", response_format="pcm", pcm_sample_rate=16000
    )
    body = b"\x00" * 32000  # 1s at 16kHz, 16-bit mono
    audio = adapter._measure(body, "u")
    assert audio.sample_rate == 16000
    assert audio.duration_seconds == pytest.approx(1.0)


def test_tts_rejects_unsupported_format() -> None:
    """mp3 cannot be measured without a decoder; refuse rather than guess."""
    with pytest.raises(TTSError, match="Unsupported response_format"):
        OpenAICompatTTSAdapter("m", "http://g/v1", response_format="mp3")


def test_tts_rejects_empty_body() -> None:
    adapter = OpenAICompatTTSAdapter("m", "http://g/v1", transport=lambda r, t: FakeResponse(b""))
    with pytest.raises(TTSError, match="no audio bytes"):
        adapter.synthesize(TTSRequest(text="x", voice="v"))


def test_tts_rejects_non_wav_body() -> None:
    adapter = OpenAICompatTTSAdapter(
        "m", "http://g/v1", transport=lambda r, t: FakeResponse(b"ID3\x03not a wav")
    )
    with pytest.raises(TTSError, match="readable WAV"):
        adapter.synthesize(TTSRequest(text="x", voice="v"))


def test_tts_unreachable_is_unavailable() -> None:
    from urllib.error import URLError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise URLError("refused")

    adapter = OpenAICompatTTSAdapter("m", "http://g/v1", transport=transport)
    with pytest.raises(TTSUnavailableError):
        adapter.synthesize(TTSRequest(text="x", voice="v"))


def test_tts_requires_base_url() -> None:
    with pytest.raises(TTSError, match="base_url is required"):
        OpenAICompatTTSAdapter("m", "")


# ==========================================================================
# factories
# ==========================================================================


def _remote_spec() -> ModelSpec:
    return ModelSpec(model="m", backend="openai_compatible", base_url="http://gpu:8000/v1")


def test_factories_build_remote_adapters() -> None:
    assert isinstance(build_asr_adapter(_remote_spec()), OpenAICompatASRAdapter)
    assert isinstance(build_vlm_adapter(_remote_spec()), OpenAICompatVLMAdapter)
    assert isinstance(build_tts_adapter(_remote_spec()), OpenAICompatTTSAdapter)


def test_factories_default_to_local_adapters() -> None:
    assert type(build_asr_adapter(ModelSpec(model="w"))).__name__ == "WhisperMLXAdapter"
    assert type(build_vlm_adapter(ModelSpec(model="v"))).__name__ == "QwenVLAdapter"
    assert type(build_tts_adapter(ModelSpec(model="t"))).__name__ == "QwenTTSAdapter"


@pytest.mark.parametrize(
    "builder,label",
    [(build_asr_adapter, "ASR"), (build_vlm_adapter, "Vision"), (build_tts_adapter, "TTS")],
)
def test_factories_reject_disabled(builder: Any, label: str) -> None:
    with pytest.raises(ValueError, match="disabled"):
        builder(ModelSpec(model="m", enabled=False))


def test_factories_pass_api_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TOK", "abc123")
    spec = ModelSpec(
        model="m",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        api_key_env="TOK",
    )
    adapter = build_vlm_adapter(spec)
    assert isinstance(adapter, OpenAICompatVLMAdapter)
    assert adapter._api_key == "abc123"
