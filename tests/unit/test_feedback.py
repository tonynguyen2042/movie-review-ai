"""T026 acceptance: adaptive sampling decisions and feedback application."""

import sqlite3
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.domain import Job, Scene, SceneAnalysis
from movie_review.media.feedback import (
    FeedbackConfig,
    additional_timestamps,
    apply_feedback,
    decide_feedback,
)
from movie_review.media.frames import FrameSamplingError, sample_movie
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _scene() -> Scene:
    return Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0)


def _analysis(**overrides: object) -> SceneAnalysis:
    data: dict[str, object] = {"scene_id": "scene_000001", "importance": 0.5}
    data.update(overrides)
    return SceneAnalysis.model_validate(data)


def test_important_scene_boosted() -> None:
    decision = decide_feedback(
        _scene(), _analysis(importance=0.9), "hello", frozenset(), base_count=3
    )
    assert decision.adjusted_count == 7
    assert decision.boosted is True
    assert any("importance" in reason for reason in decision.reasons)


def test_action_boost() -> None:
    decision = decide_feedback(_scene(), _analysis(actions=["runs"]), "", frozenset(), base_count=3)
    assert decision.adjusted_count == 5


def test_new_characters_boost() -> None:
    decision = decide_feedback(
        _scene(), _analysis(characters=["A", "B"]), "", frozenset(), base_count=3
    )
    assert decision.adjusted_count == 7
    known = decide_feedback(
        _scene(), _analysis(characters=["A"]), "", frozenset({"A"}), base_count=3
    )
    assert known.adjusted_count == 3


def test_low_information_halved_to_floor() -> None:
    decision = decide_feedback(_scene(), _analysis(importance=0.1), "", frozenset(), base_count=3)
    assert decision.adjusted_count == 2
    assert decision.boosted is False
    assert any("halved" in reason for reason in decision.reasons)


def test_count_clamped() -> None:
    decision = decide_feedback(_scene(), _analysis(importance=0.9), "", frozenset(), base_count=30)
    assert decision.adjusted_count == 24


def test_additional_timestamps_avoid_existing() -> None:
    assert additional_timestamps([0.0, 2.5], 0.0, 5.0, 4) == [1.25, 3.75]
    assert additional_timestamps([0.0, 1.0], 0.0, 5.0, 2) == []
    assert additional_timestamps([], 2.0, 2.0, 4) == []


def _fake_run(binary: str, args: list[str]) -> str:
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"frame-bytes")
    return ""


def _setup(tmp_path: Path) -> tuple[sqlite3.Connection, Path, Path]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    repo.save_scene(conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    jobs_dir = tmp_path / "jobs"
    cache = CacheManager(tmp_path / "cache")
    sample_movie(
        source,
        [("scene_000001", 0.0, 5.0)],
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        run_fn=_fake_run,
    )
    return conn, jobs_dir, source


def _analyses(importance: float) -> dict[str, tuple[SceneAnalysis, str]]:
    return {
        "scene_000001": (
            SceneAnalysis(scene_id="scene_000001", importance=importance),
            "hello",
        )
    }


def test_apply_feedback_adds_frames(tmp_path: Path) -> None:
    conn, jobs_dir, source = _setup(tmp_path)
    cache = CacheManager(tmp_path / "cache")
    before = repo.get_artifact(conn, "job_1-frames")
    assert before is not None
    result = apply_feedback(
        source,
        _analyses(0.9),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        run_fn=_fake_run,
    )
    assert result.decisions[0].boosted is True
    assert len(result.added) == 4
    assert all(frame.path.is_file() for frame in result.added)
    after = repo.get_artifact(conn, "job_1-frames")
    assert after is not None
    assert after.output_hash != before.output_hash
    # Second pass reads the updated manifest: budget already covered.
    again = apply_feedback(
        source,
        _analyses(0.9),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        run_fn=_fake_run,
    )
    assert again.added == []


def test_apply_feedback_requires_prior_sampling(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")
    with pytest.raises(FrameSamplingError, match="sampling before feedback"):
        apply_feedback(
            source,
            _analyses(0.9),
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            run_fn=_fake_run,
        )


def test_feedback_config_defaults() -> None:
    config = FeedbackConfig()
    assert (config.important_bonus, config.action_bonus) == (4, 2)
