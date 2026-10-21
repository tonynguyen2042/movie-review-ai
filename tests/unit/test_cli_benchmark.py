"""The benchmark command must exist and produce measurements.

T154. README §75 lists the measurements: model load time, throughput, the
realtime factors, peak memory and the pipeline duration. §76 says the
pipeline benchmark runs on a short reference movie, and §56 says the exact
model sizes "SHALL be benchmarked on the target Mac rather than hard-coded".

The three measurement functions already existed in `benchmark/`. None of them
had a command, so the numbers could not be taken.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.benchmark.runner import (
    BENCHMARK_SLOTS,
    BenchmarkError,
    _probe_wav,
    run_model_benchmark,
    run_pipeline_benchmark,
)
from movie_review.cli.app import app
from movie_review.config.settings import load_settings


def test_the_command_exists() -> None:
    """The measurement functions existed; no command reached them."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "benchmark" in result.output


def test_the_pipeline_mode_needs_a_movie() -> None:
    result = CliRunner().invoke(app, ["benchmark", "--mode", "pipeline"])
    assert result.exit_code == 2
    assert "needs --movie" in (result.stdout or "") + (result.stderr or "")


def test_the_model_mode_needs_a_slot() -> None:
    result = CliRunner().invoke(app, ["benchmark", "--mode", "model"])
    assert result.exit_code == 2
    assert "needs --slot" in (result.stdout or "") + (result.stderr or "")


def test_an_unknown_mode_is_rejected() -> None:
    result = CliRunner().invoke(app, ["benchmark", "--mode", "nope", "--slot", "reasoning"])
    assert result.exit_code == 2
    assert "Unknown --mode" in (result.stdout or "") + (result.stderr or "")


def test_an_unknown_slot_is_rejected(tmp_path: Path) -> None:
    settings = load_settings()
    with pytest.raises(BenchmarkError, match="Unknown benchmark slot"):
        run_model_benchmark(settings, "nope", tmp_path)


def test_every_advertised_slot_is_accepted(tmp_path: Path) -> None:
    """The list of slots and the code that handles them must agree."""
    import movie_review.benchmark.runner as runner_module

    source = Path(runner_module.__file__).read_text(encoding="utf-8")
    for slot in BENCHMARK_SLOTS:
        assert f'if slot == "{slot}"' in source, f"{slot} is advertised but not handled"


def test_the_probe_audio_is_a_valid_wav(tmp_path: Path) -> None:
    """The ASR benchmark needs a file it can actually read."""
    import wave

    path = _probe_wav(tmp_path / "probe.wav")
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 16000


def test_the_pipeline_benchmark_reports_per_stage_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline benchmark reports the time each stage took."""

    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00")

    class _Result:
        def __init__(self, stage: str, ok: bool) -> None:
            self.stage = stage
            self.success = ok
            self.duration_ms = 1200

    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator.run_pipeline",
        lambda *a, **k: [_Result("ingest", True), _Result("scenes", True)],
    )
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    settings = load_settings()

    report = run_pipeline_benchmark(str(movie), str(tmp_path / "jobs.db"), settings)
    assert report["mode"] == "pipeline"
    assert [item["stage"] for item in report["stages"]] == ["ingest", "scenes"]
    assert report["stages"][0]["seconds"] == 1.2
    assert report["slowest"]["stage"] in ("ingest", "scenes")


def test_the_pipeline_benchmark_needs_a_real_movie(tmp_path: Path) -> None:
    settings = load_settings()
    with pytest.raises(BenchmarkError, match="not found"):
        run_pipeline_benchmark(str(tmp_path / "missing.mp4"), None, settings)


def test_the_command_prints_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The output has to be readable by a machine."""

    class _Result:
        stage = "ingest"
        success = True
        duration_ms = 1000

    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator.run_pipeline", lambda *a, **k: [_Result()]
    )
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00")

    result = CliRunner().invoke(app, ["benchmark", "--mode", "pipeline", "--movie", str(movie)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["mode"] == "pipeline"
    assert document["stages"][0]["stage"] == "ingest"
