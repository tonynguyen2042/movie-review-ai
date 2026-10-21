"""The CLI flags README section 49 and 74 name have to exist and work.

T155. README §49 lists `--from-stage`, `--to-stage` and `--force`; §74
lists `--deterministic`; §83 lists `--keep-intermediates`. None of them
existed.

`--deterministic` needed more than a flag: the sampling had to become part
of the configuration, part of the model adapters, and part of the cache
identity, so a pinned run and an ordinary one do not share answers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import _deterministic_generation, _reconcile_stage_flag, app
from movie_review.config.settings import GenerationSettings, generation_config, load_settings
from movie_review.domain import Job
from movie_review.pipeline.cleanup import cleanup_intermediates
from movie_review.pipeline.force import invalidate_artifacts
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def test_the_flags_exist() -> None:
    """README sections 49, 74 and 83 name them; none existed."""
    result = CliRunner().invoke(app, ["process", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--from-stage",
        "--to-stage",
        "--force",
        "--deterministic",
        "--keep-intermediates",
    ):
        assert flag in result.output, f"{flag} is missing"


def test_the_two_stage_flag_names_reconcile() -> None:
    """The README names --from-stage; --stage-from is the older alias."""
    assert _reconcile_stage_flag("--from-stage", "ingest", "--stage-from", None) == "ingest"
    assert _reconcile_stage_flag("--from-stage", None, "--stage-from", "ingest") == "ingest"


def test_giving_both_stage_names_is_a_usage_error() -> None:
    """A silent preference would leave the operator guessing."""
    import typer

    with pytest.raises(typer.BadParameter):
        _reconcile_stage_flag("--from-stage", "ingest", "--stage-from", "scenes")


def test_the_deterministic_sampling_is_pinned() -> None:
    """A reproducible run needs a fixed seed, a fixed temperature and a fixed top-p."""
    generation = _deterministic_generation()
    assert generation.seed == 0
    assert generation.temperature == 0.0
    assert generation.top_p == 1.0


def test_the_pinned_sampling_reaches_every_model_slot() -> None:
    """A run is reproducible only if every slot is pinned."""
    settings = load_settings(generation=_deterministic_generation())
    for name in ("asr", "vision", "reasoning", "critic", "tts"):
        spec = getattr(settings.models, name)
        assert spec.generation.seed == 0, f"{name} is not pinned"
        assert spec.generation.temperature == 0.0, f"{name} is not pinned"


def test_the_sampling_is_part_of_the_cache_identity() -> None:
    """Two runs with a different temperature are two different answers."""
    settings = load_settings()
    pinned = load_settings(generation=_deterministic_generation())
    assert generation_config(settings.models.reasoning) != generation_config(
        pinned.models.reasoning
    )


def test_the_sampling_reaches_the_adapters() -> None:
    """The adapter has to send the seed and the top-p, not just store them."""
    from movie_review.reasoning.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(
        "m",
        "http://gpu:8000/v1",
        generation=GenerationSettings(seed=7, temperature=0.25, top_p=0.8),
    )
    payload = adapter._payload("hello", 0.25)
    assert payload["seed"] == 7
    assert payload["top_p"] == 0.8


def test_the_cleanup_removes_the_frames_and_keeps_the_manifest(tmp_path: Path) -> None:
    """The manifest is the record of what was sampled; the images are the bulk."""
    job_dir = tmp_path / "job_1"
    frames = job_dir / "frames" / "scene_000001"
    frames.mkdir(parents=True)
    (frames / "frame.jpg").write_bytes(b"\x00")
    (job_dir / "frames" / "frames.json").write_text("{}", encoding="utf-8")

    removed = cleanup_intermediates(job_dir)

    assert removed
    assert not (frames / "frame.jpg").exists()
    assert (job_dir / "frames" / "frames.json").is_file()


def test_keeping_the_intermediates_keeps_the_frames(tmp_path: Path) -> None:
    job_dir = tmp_path / "job_1"
    frames = job_dir / "frames" / "scene_000001"
    frames.mkdir(parents=True)
    (frames / "frame.jpg").write_bytes(b"\x00")

    assert cleanup_intermediates(job_dir, keep=True) == []
    assert (frames / "frame.jpg").exists()


def test_forcing_removes_the_recorded_artifacts(tmp_path: Path) -> None:
    """`--force` means redo the work, so the artifacts have to go."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
        jobs_dir = tmp_path / "jobs"
        artifact = jobs_dir / "job_1" / "story" / "movie-analysis.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")
        from movie_review.domain import Artifact

        repo.save_artifact(
            conn,
            Artifact(
                artifact_id="job_1-story",
                job_id="job_1",
                stage="story",
                relative_path="story/movie-analysis.json",
                version=1,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                input_hash="a" * 64,
                output_hash="b" * 64,
            ),
        )

        removed = invalidate_artifacts(conn, "job_1", ["story"], jobs_dir)

        assert removed == ["story/movie-analysis.json"]
        assert not artifact.exists()
        assert repo.get_artifact(conn, "job_1-story") is None
        # The job itself is untouched.
        assert repo.get_job(conn, "job_1") is not None
    finally:
        conn.close()


def test_forcing_leaves_the_other_stages_alone(tmp_path: Path) -> None:
    """Only the selected stages are redone."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
        jobs_dir = tmp_path / "jobs"
        from movie_review.domain import Artifact

        for stage in ("story", "render"):
            path = jobs_dir / "job_1" / stage / "artifact.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            repo.save_artifact(
                conn,
                Artifact(
                    artifact_id=f"job_1-{stage}",
                    job_id="job_1",
                    stage=stage,
                    relative_path=f"{stage}/artifact.json",
                    version=1,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    input_hash="a" * 64,
                    output_hash="b" * 64,
                ),
            )

        invalidate_artifacts(conn, "job_1", ["story"], jobs_dir)

        assert repo.get_artifact(conn, "job_1-story") is None
        assert repo.get_artifact(conn, "job_1-render") is not None
    finally:
        conn.close()


def test_the_job_keeps_the_intermediate_flag(tmp_path: Path) -> None:
    """The flag has to survive a reload, or a resume forgets it."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4", keep_intermediates=True))
        loaded = repo.get_job(conn, "job_1")
        assert loaded is not None
        assert loaded.keep_intermediates is True
    finally:
        conn.close()
