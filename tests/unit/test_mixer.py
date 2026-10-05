"""T060 acceptance: narration-first mixing with ducked music."""

import math
import struct
import wave
from pathlib import Path

import pytest

from movie_review.rendering.audio import MixError, ducking_envelope, mix, read_wav

RATE = 16000


def _tone(path: Path, seconds: float, amplitude: int = 8000, rate: int = RATE) -> Path:
    frames = bytearray()
    count = int(seconds * rate)
    for index in range(count):
        frames += struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * index / rate)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return path


def _silence_then_tone(path: Path) -> Path:
    frames = bytearray()
    for index in range(2 * RATE):
        sample = 0 if index < RATE else int(8000 * math.sin(2 * math.pi * 440 * index / RATE))
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(bytes(frames))
    return path


def test_narration_only_normalized(tmp_path: Path) -> None:
    narration = _tone(tmp_path / "n.wav", 1.0)
    result = mix(narration, tmp_path / "out.wav")
    assert result.duration_seconds == pytest.approx(1.0)
    assert result.peak == pytest.approx(0.89, abs=0.01)
    assert result.path.is_file()


def test_music_ducked_under_narration(tmp_path: Path) -> None:
    narration = _silence_then_tone(tmp_path / "n.wav")
    music = _tone(tmp_path / "m.wav", 2.0, amplitude=4000)
    result = mix(narration, tmp_path / "out.wav", music)
    mixed, _ = read_wav(result.path)
    first_half = abs(mixed[:RATE]).mean()
    second_half = abs(mixed[RATE:]).mean()
    assert second_half > first_half


def test_music_trimmed_to_narration(tmp_path: Path) -> None:
    narration = _tone(tmp_path / "n.wav", 1.0)
    music = _tone(tmp_path / "m.wav", 3.0)
    result = mix(narration, tmp_path / "out.wav", music)
    assert result.duration_seconds == pytest.approx(1.0)


def test_rate_mismatch_rejected(tmp_path: Path) -> None:
    narration = _tone(tmp_path / "n.wav", 1.0)
    music = _tone(tmp_path / "m.wav", 1.0, rate=8000)
    with pytest.raises(MixError, match="rate"):
        mix(narration, tmp_path / "out.wav", music)


def test_missing_and_stereo_rejected(tmp_path: Path) -> None:
    with pytest.raises(MixError, match="Cannot read"):
        mix(tmp_path / "absent.wav", tmp_path / "out.wav")
    stereo = tmp_path / "st.wav"
    with wave.open(str(stereo), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(b"\x00\x00" * 2 * RATE)
    with pytest.raises(MixError, match="16-bit mono"):
        mix(stereo, tmp_path / "out.wav")


def test_ducking_envelope() -> None:
    full = ducking_envelope(100, [(0.0, 10.0)], 10)
    assert (full == 0.25).all()
    empty = ducking_envelope(100, [], 10)
    assert (empty == 1.0).all()
    partial = ducking_envelope(100, [(0.2, 0.5)], 100)
    assert partial[0] == 1.0
    assert partial[30] == pytest.approx(0.25)
