"""T093 acceptance: script editor loads and exports data."""

import json
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.ui.script_editor import ScriptEditor


def test_script_editor_from_script(tmp_path: Path) -> None:
    """Script editor can be built from review-script.json."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    # Create a minimal review-script.json
    script = {
        "job_id": job_id,
        "stage": "review",
        "stage_version": "v1",
        "prompt": "script_writer:v1",
        "model": "Qwen3.5-27B",
        "word_count": 100,
        "script": {
            "sections": [
                {
                    "id": "section_01",
                    "type": "hook",
                    "target_seconds": 45,
                    "purpose": "Open with the central mystery",
                    "event_ids": ["event_00001"],
                    "paragraphs": [
                        {
                            "id": "p1",
                            "text": "The movie opens with a mystery.",
                            "claims": [
                                {
                                    "claim_id": "c1",
                                    "text": "Movie opens with mystery",
                                    "type": "PLOT_FACT",
                                    "evidence": ["ev1"],
                                }
                            ],
                            "target_seconds": 10.0,
                        }
                    ],
                },
                {
                    "id": "section_02",
                    "type": "climax",
                    "target_seconds": 150,
                    "purpose": "Retell the climax",
                    "event_ids": ["event_00002"],
                    "paragraphs": [
                        {
                            "id": "p2",
                            "text": "The climax reveals the truth.",
                            "claims": [
                                {
                                    "claim_id": "c2",
                                    "text": "Climax reveals truth",
                                    "type": "PLOT_FACT",
                                    "evidence": ["ev2"],
                                }
                            ],
                            "target_seconds": 20.0,
                        }
                    ],
                },
            ],
        },
    }

    artifacts.write_json(job_dir / "review-script.json", script)

    editor = ScriptEditor(jobs_dir, job_id)
    data = editor.load()

    assert data["job_id"] == job_id
    assert data["total_sections"] == 2
    assert data["total_paragraphs"] == 2
    assert data["total_words"] > 0
    assert len(data["sections"]) == 2
    # Sections sorted by id
    assert data["sections"][0]["id"] == "section_01"
    assert data["sections"][1]["id"] == "section_02"
    # Paragraphs have word counts
    assert data["sections"][0]["paragraphs"][0]["word_count"] > 0


def test_script_editor_json_export(tmp_path: Path) -> None:
    """Script editor can export to JSON."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    script = {
        "job_id": job_id,
        "stage": "review",
        "stage_version": "v1",
        "prompt": "script_writer:v1",
        "model": "Qwen3.5-27B",
        "word_count": 50,
        "script": {"sections": []},
    }
    artifacts.write_json(job_dir / "review-script.json", script)

    editor = ScriptEditor(jobs_dir, job_id)
    json_str = editor.to_json()

    data = json.loads(json_str)
    assert data["job_id"] == job_id


def test_script_editor_html_export(tmp_path: Path) -> None:
    """Script editor can export to HTML."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    script = {
        "job_id": job_id,
        "stage": "review",
        "stage_version": "v1",
        "prompt": "script_writer:v1",
        "model": "Qwen3.5-27B",
        "word_count": 50,
        "script": {
            "sections": [
                {
                    "id": "section_01",
                    "type": "hook",
                    "target_seconds": 45,
                    "purpose": "Open with the central mystery",
                    "event_ids": ["event_00001"],
                    "paragraphs": [
                        {
                            "id": "p1",
                            "text": "The movie opens with a mystery.",
                            "claims": [],
                            "target_seconds": 10.0,
                        }
                    ],
                }
            ],
        },
    }
    artifacts.write_json(job_dir / "review-script.json", script)

    editor = ScriptEditor(jobs_dir, job_id)
    html = editor.to_html()

    assert "Script Editor" in html
    assert "Job" in html
    assert "Save Changes" in html
    assert "data = " in html


def test_script_editor_empty(tmp_path: Path) -> None:
    """Script editor returns empty structure when no script file."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    editor = ScriptEditor(jobs_dir, job_id)
    data = editor.load()

    assert data["job_id"] == job_id
    assert data["sections"] == []
    assert data["total_sections"] == 0
    assert data["total_paragraphs"] == 0
    assert data["total_words"] == 0
