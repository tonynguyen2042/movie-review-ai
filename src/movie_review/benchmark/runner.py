"""The benchmark command: measure the models and the pipeline.

README section 75 lists the measurements: model load time, generation
throughput, vision frames per second, the ASR and TTS realtime factors,
peak and average memory, and the pipeline duration. Section 76 says the
pipeline benchmark runs on a short reference movie, and section 56 says the
exact Qwen3-VL size "SHALL be benchmarked on the target Mac rather than
hard-coded".

The three measurement functions already existed in `benchmark/`. None of them
had a command, so the numbers could not be taken.
"""

from __future__ import annotations

import logging
import time
import wave
from pathlib import Path
from typing import Any

from movie_review.domain.tts import TTSRequest
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: The model slots that can be benchmarked, and what one unit of work is for
#: each. The unit is the smallest thing the slot can do, so the number
#: means something: one completion, one synthesis, one second of audio
#: transcribed, one frame analysed.
BENCHMARK_SLOTS = ("reasoning", "tts", "asr", "vision")

#: The text the reasoning and TTS benchmarks use. It is deliberately tiny:
#: the measurement is the overhead, not the quality.
PROBE_TEXT = "Reply with the single word: ok."

#: The tone the ASR benchmark transcribes. It is silence, not speech: the
#: measurement is the speed, not the accuracy.
PROBE_SECONDS = 1.0
PROBE_RATE = 16000


class BenchmarkError(Exception):
    """A benchmark could not be run."""


def _probe_wav(path: Path, seconds: float = PROBE_SECONDS, rate: int = PROBE_RATE) -> Path:
    """A silent mono WAV, for the ASR benchmark to transcribe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _slot_spec(settings: Any, slot: str) -> Any:
    """The configured model spec for a benchmark slot."""
    if slot == "translation":
        return settings.models.effective_translation
    return getattr(settings.models, slot)


def _build_adapter(settings: Any, slot: str) -> Any:
    """The adapter for a benchmark slot."""
    spec = _slot_spec(settings, slot)
    if slot == "reasoning":
        from movie_review.reasoning.factory import build_reasoning_adapter

        return build_reasoning_adapter(spec)
    if slot == "tts":
        from movie_review.tts.factory import build_tts_adapter

        return build_tts_adapter(spec)
    if slot == "asr":
        from movie_review.asr.factory import build_asr_adapter

        return build_asr_adapter(spec)
    if slot == "vision":
        from movie_review.vision.factory import build_vlm_adapter

        return build_vlm_adapter(spec)
    raise BenchmarkError(f"Unknown benchmark slot: {slot}")


def _one_unit(
    adapter: Any,
    slot: str,
    workdir: Path,
    movie: str | None,
) -> Any:
    """The callable that performs one unit of the slot's work."""
    if slot == "reasoning":
        return lambda: adapter.complete(PROBE_TEXT)
    if slot == "tts":
        return lambda: adapter.synthesize(
            TTSRequest(text=PROBE_TEXT, voice="default", emotion="neutral", speed=1.0)
        )
    if slot == "asr":
        audio = _probe_wav(workdir / "probe.wav")
        return lambda: adapter.transcribe(audio, language=None)
    if slot == "vision":
        if not movie:
            raise BenchmarkError("The vision benchmark needs a movie to take a frame from")
        return _vision_unit(adapter, Path(movie), workdir)
    raise BenchmarkError(f"Unknown benchmark slot: {slot}")


def _vision_unit(adapter: Any, movie: Path, workdir: Path) -> Any:
    """One frame analysed, so the vision benchmark measures a real request."""
    from movie_review.media.frames import extract_frame
    from movie_review.vision.port import AnalysisInput

    frame = workdir / "probe.jpg"
    extract_frame(movie, 1.0, frame)
    return lambda: adapter.analyze(
        AnalysisInput(scene_id="probe", frames=[frame], dialogue="", previous_summary=None),
        "Describe what is visible in this frame.",
    )


def run_model_benchmark(
    settings: Any,
    slot: str,
    workdir: Path,
    *,
    repeats: int = 3,
    movie: str | None = None,
) -> dict[str, Any]:
    """Measure one slot: load time, throughput and peak memory."""
    from movie_review.benchmark.memory import benchmark_memory
    from movie_review.benchmark.models import benchmark_operation

    if slot not in BENCHMARK_SLOTS:
        raise BenchmarkError(f"Unknown benchmark slot: {slot}. Expected one of {BENCHMARK_SLOTS}.")

    adapter = _build_adapter(settings, slot)
    workdir.mkdir(parents=True, exist_ok=True)

    load_started = time.perf_counter()
    unit = _one_unit(adapter, slot, workdir, movie)
    # The first call loads the model, so it is timed on its own.
    unit()
    load_seconds = time.perf_counter() - load_started

    result = benchmark_operation(slot, _slot_spec(settings, slot).model, unit, repeats=repeats)
    memory = benchmark_memory(slot, unit)

    with ulog.logging_context(stage="benchmark"):
        ulog.log_event(
            _logger,
            event="benchmark.model",
            status="ok",
            slot=slot,
            load_seconds=load_seconds,
            mean_seconds=result.mean_seconds,
        )
    return {
        "mode": "model",
        "slot": slot,
        "model": result.model,
        "load_seconds": load_seconds,
        "repeats": result.repeats,
        "mean_seconds": result.mean_seconds,
        "p50_seconds": result.p50_seconds,
        "min_seconds": result.min_seconds,
        "max_seconds": result.max_seconds,
        "throughput_per_sec": result.throughput_per_sec,
        "peak_memory_mb": memory.peak_mb,
    }


def run_pipeline_benchmark(
    movie: str,
    db_path: str | None,
    settings: Any,
) -> dict[str, Any]:
    """Measure the pipeline on a reference movie, stage by stage."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE, run_pipeline

    source = Path(movie)
    if not source.is_file():
        raise BenchmarkError(f"Input file not found: {movie}")

    from movie_review.jobs.manager import JobManager
    from movie_review.storage.database import bootstrap

    conn = __import__("sqlite3").connect(str(bootstrap(Path(settings.paths.data_dir) / "jobs.db")))
    conn.row_factory = __import__("sqlite3").Row
    manager = JobManager(conn)
    with conn:
        job = manager.create(str(source))

    timings: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        results = run_pipeline(job.job_id, str(source), db_path)
    finally:
        total = time.perf_counter() - started
        conn.close()

    for result in results:
        timings.append(
            {
                "stage": result.stage,
                "seconds": result.duration_ms / 1000.0,
                "success": result.success,
            }
        )

    slowest = max(timings, key=lambda item: item["seconds"], default=None)
    return {
        "mode": "pipeline",
        "job_id": job.job_id,
        "movie": str(source),
        "total_seconds": total,
        "stages": timings,
        "slowest": slowest,
        "stage_count": len(timings),
        "pipeline_stage_count": len(STAGE_SEQUENCE),
    }
