"""T021 acceptance: energy diarizer finds speech spans honestly."""

import math
import struct
import wave
from pathlib import Path

import pytest

from movie_review.diarization.initial import (
    EnergyDiarizer,
    VadConfig,
    detect_speech_spans,
    read_mono_pcm16,
)
from movie_review.diarization.port import DiarizationError, DiarizationPort
from movie_review.media import ffmpeg as ff

RATE = 16000


def _write_wav__diarization(path: Path, parts: list[tuple[float, bool]], rate: int = RATE) -> Path:
    """Write mono 16-bit WAV; each part is (seconds, tone-or-silence)."""
    frames = bytearray()
    for seconds, tone in parts:
        count = int(seconds * rate)
        for index in range(count):
            sample = int(8000 * math.sin(2 * math.pi * 440 * index / rate)) if tone else 0
            frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return path


def test_two_bursts_two_spans(tmp_path: Path) -> None:
    wav = _write_wav__diarization(
        tmp_path / "s.wav", [(0.5, False), (1.0, True), (0.6, False), (1.0, True)]
    )
    segments = EnergyDiarizer().diarize(wav)
    assert [s.speaker for s in segments] == ["SPEAKER_00", "SPEAKER_00"]
    assert segments[0].start == pytest.approx(0.5, abs=0.2)
    assert segments[0].end == pytest.approx(1.5, abs=0.2)
    assert segments[1].start == pytest.approx(2.1, abs=0.2)
    assert segments[1].end == pytest.approx(3.1, abs=0.2)


def test_silence_is_empty(tmp_path: Path) -> None:
    wav = _write_wav__diarization(tmp_path / "s.wav", [(2.0, False)])
    assert EnergyDiarizer().diarize(wav) == []


def test_short_blip_dropped(tmp_path: Path) -> None:
    wav = _write_wav__diarization(tmp_path / "s.wav", [(0.1, True)])
    assert EnergyDiarizer().diarize(wav) == []


def test_brief_gap_merged(tmp_path: Path) -> None:
    wav = _write_wav__diarization(tmp_path / "s.wav", [(1.0, True), (0.2, False), (1.0, True)])
    assert len(EnergyDiarizer().diarize(wav)) == 1


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DiarizationError, match="not found"):
        EnergyDiarizer().diarize(tmp_path / "absent.wav")


def test_unsupported_width_rejected(tmp_path: Path) -> None:
    wav = tmp_path / "s8.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(RATE)
        handle.writeframes(b"\x80" * RATE)
    with pytest.raises(DiarizationError, match="16-bit"):
        EnergyDiarizer().diarize(wav)


def test_wrong_rate_rejected(tmp_path: Path) -> None:
    wav = _write_wav__diarization(tmp_path / "s.wav", [(0.5, True)], rate=8000)
    with pytest.raises(DiarizationError, match="8000 Hz"):
        EnergyDiarizer().diarize(wav)


def test_threshold_configurable(tmp_path: Path) -> None:
    wav = _write_wav__diarization(tmp_path / "s.wav", [(1.0, True)])
    strict = VadConfig(silence_threshold=100000.0)
    assert EnergyDiarizer(strict).diarize(wav) == []
    assert len(EnergyDiarizer().diarize(wav)) == 1


def test_detect_speech_spans_pure() -> None:
    import numpy as np

    samples = np.zeros(16000)
    samples[8000:] = 5000.0
    spans = detect_speech_spans(samples, VadConfig())
    assert len(spans) == 1
    assert spans[0][0] == pytest.approx(0.5, abs=0.2)
    assert detect_speech_spans(np.zeros(100), VadConfig()) == []


def test_port_contract(tmp_path: Path) -> None:
    diarizer = EnergyDiarizer()
    assert isinstance(diarizer, DiarizationPort)
    diarizer.unload()
    wav = _write_wav__diarization(tmp_path / "s.wav", [(0.5, True)])
    assert len(diarizer.diarize(wav)) == 1


@pytest.mark.ffmpeg
def test_non_wav_decoded(tmp_path: Path) -> None:
    source = tmp_path / "tone.m4a"
    ff.check(
        "ffmpeg",
        ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(source)],
    )
    segments = EnergyDiarizer().diarize(source)
    assert len(segments) == 1
    assert segments[0].speaker == "SPEAKER_00"


def test_read_mono_pcm16_stereo_averaged(tmp_path: Path) -> None:
    wav = tmp_path / "st.wav"
    frames = bytearray()
    for _ in range(RATE):
        frames += struct.pack("<hh", 8000, -8000)
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))
    samples = read_mono_pcm16(wav)
    assert samples.shape == (RATE,)
