"""T094 acceptance: visual timeline editor loads and exports data."""

import json
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.ui.timeline_editor import VisualTimelineEditor


def test_timeline_editor_from_manifest(tmp_path: Path) -> None:
    """Timeline editor can be built from render-manifest.json."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    # Create a minimal render-manifest.json
    manifest = {
        "job_id": job_id,
        "stage": "render",
        "stage_version": "v1",
        "manifest": {
            "segments": [
                {
                    "paragraph_id": "p1",
                    "scene_id": "scene_000001",
                    "clip_start": 0.0,
                    "clip_end": 10.0,
                    "start": 0.0,
                    "duration": 10.0,
                    "loop_clip": False,
                },
                {
                    "paragraph_id": "p2",
                    "scene_id": "scene_000002",
                    "clip_start": 5.0,
                    "clip_end": 15.0,
                    "start": 10.0,
                    "duration": 15.0,
                    "loop_clip": True,
                },
            ],
            "total_seconds": 25.0,
            "source_seconds": 20.0,
        },
    }

    (job_dir / "render").mkdir()
    artifacts.write_json(job_dir / "render" / "render-manifest.json", manifest)

    editor = VisualTimelineEditor(jobs_dir, job_id)
    data = editor.load()

    assert data["job_id"] == job_id
    assert data["clip_count"] == 2
    assert data["total_duration"] == 25.0
    assert len(data["tracks"]) == 3  # video, audio, subtitles

    # Check video track
    video_track = next(t for t in data["tracks"] if t["id"] == "video")
    assert len(video_track["clips"]) == 2
    assert video_track["clips"][0]["paragraph_id"] == "p1"
    assert video_track["clips"][1]["paragraph_id"] == "p2"

    # Check audio track
    audio_track = next(t for t in data["tracks"] if t["id"] == "audio")
    assert len(audio_track["clips"]) == 2

    # Check subtitle track
    subtitle_track = next(t for t in data["tracks"] if t["id"] == "subtitles")
    assert len(subtitle_track["clips"]) == 2


def test_timeline_editor_json_export(tmp_path: Path) -> None:
    """Timeline editor can export to JSON."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    manifest = {
        "job_id": job_id,
        "stage": "render",
        "stage_version": "v1",
        "manifest": {"segments": []},
    }
    (job_dir / "render").mkdir()
    artifacts.write_json(job_dir / "render" / "render-manifest.json", manifest)

    editor = VisualTimelineEditor(jobs_dir, job_id)
    json_str = editor.to_json()

    data = json.loads(json_str)
    assert data["job_id"] == job_id


def test_timeline_editor_html_export(tmp_path: Path) -> None:
    """Timeline editor can export to HTML."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    manifest = {
        "job_id": job_id,
        "stage": "render",
        "stage_version": "v1",
        "manifest": {
            "segments": [
                {
                    "paragraph_id": "p1",
                    "scene_id": "s1",
                    "clip_start": 0.0,
                    "clip_end": 10.0,
                    "start": 0.0,
                    "duration": 10.0,
                    "loop_clip": False,
                }
            ],
        },
    }
    (job_dir / "render").mkdir()
    artifacts.write_json(job_dir / "render" / "render-manifest.json", manifest)

    editor = VisualTimelineEditor(jobs_dir, job_id)
    html = editor.to_html()

    assert "Visual Timeline Editor" in html
    assert "Job" in html
    assert "Save Timeline" in html
    assert "data = " in html


def test_timeline_editor_empty(tmp_path: Path) -> None:
    """Timeline editor returns empty structure when no manifest file."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    editor = VisualTimelineEditor(jobs_dir, job_id)
    data = editor.load()

    assert data["job_id"] == job_id
    assert data["clip_count"] == 0
    assert data["total_duration"] == 0.0
    assert len(data["tracks"]) == 3
