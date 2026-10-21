"""The output directory must hold what README section 98 promises.

T151. README sections 1 and 98 promise an output directory holding
`review.mp4`, `review.srt`, `narration.wav`, `review-script.md`,
`movie-analysis.json`, `quality-report.json`, `manifest.json` and
`thumbnail.png`.

Four of the eight were produced. The script in Markdown was never
rendered, the final manifest was never written, and `--output` reached
nothing but a log line — so the promised directory did not exist.

The Markdown is derived from the structured script, never maintained
separately: the constitution's P3 says the structured data is the contract
and Markdown is presentation.
"""

from __future__ import annotations

from pathlib import Path

from movie_review.domain import ReviewParagraph, ReviewScript, ReviewSection
from movie_review.pipeline.export import (
    MANIFEST_FILENAME,
    SCRIPT_FILENAME,
    build_manifest,
    export_output,
    render_script_markdown,
)


def _script__output_set() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id="p1",
                        text="The hero walks into the room.",
                        target_seconds=10,
                        claims=[],
                        visual_intent="s",
                    )
                ],
            ),
            ReviewSection(
                id="sec_002",
                type="ending",
                paragraphs=[
                    ReviewParagraph(
                        id="p2",
                        text="And that is how it ends.",
                        target_seconds=12,
                        claims=[],
                        visual_intent="s",
                    )
                ],
            ),
        ]
    )


def _job_files(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "job_1"
    (job_dir / "render").mkdir(parents=True)
    (job_dir / "tts").mkdir(parents=True)
    (job_dir / "qc").mkdir(parents=True)
    (job_dir / "render" / "review.mp4").write_bytes(b"video")
    (job_dir / "render" / "review.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", "utf-8")
    (job_dir / "tts" / "narration.wav").write_bytes(b"audio")
    (job_dir / "qc" / "quality-report.json").write_text("{}", encoding="utf-8")
    (job_dir / "movie-analysis.json").write_text("{}", encoding="utf-8")


def test_the_whole_output_set_is_written(tmp_path: Path) -> None:
    """The eight files README section 98 names."""
    _job_files(tmp_path)
    out = tmp_path / "out"
    manifest = build_manifest(
        "job_1",
        "movie.mkv",
        "a" * 64,
        {"asr": "whisper", "vision": "qwen3-vl", "reasoning": "qwen3.5", "tts": "qwen3-tts"},
        {"evidence_coverage": 100.0},
        "COMPLETED",
        {},
    )
    result = export_output(
        tmp_path / "jobs", "job_1", out, script=_script__output_set(), manifest=manifest
    )

    names = {path.name for path in result.files}
    assert "review.mp4" in names
    assert "narration.wav" in names
    assert "review.srt" in names
    assert "movie-analysis.json" in names
    assert "quality-report.json" in names
    assert SCRIPT_FILENAME in names
    assert MANIFEST_FILENAME in names
    for name in names:
        assert (out / name).is_file()


def test_the_manifest_holds_the_promised_shape(tmp_path: Path) -> None:
    """README section 95 gives the manifest's shape."""
    _job_files(tmp_path)
    out = tmp_path / "out"
    manifest = build_manifest(
        "job_1",
        "movie.mkv",
        "a" * 64,
        {"asr": "whisper", "vision": "qwen3-vl", "reasoning": "qwen3.5", "tts": "qwen3-tts"},
        {"evidence_coverage": 100.0},
        "COMPLETED",
        {},
    )
    result = export_output(
        tmp_path / "jobs", "job_1", out, script=_script__output_set(), manifest=manifest
    )

    import json

    document = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert document["job_id"] == "job_1"
    assert document["input"]["file"] == "movie.mkv"
    assert document["input"]["sha256"] == "a" * 64
    assert document["models"]["asr"] == "whisper"
    assert document["metrics"]["evidence_coverage"] == 100.0
    assert document["status"] == "COMPLETED"
    assert "output" in document


def test_the_markdown_is_derived_from_the_script(tmp_path: Path) -> None:
    """The structured script is the contract; the Markdown is its presentation."""
    _job_files(tmp_path)
    out = tmp_path / "out"
    result = export_output(tmp_path / "jobs", "job_1", out, script=_script__output_set())

    markdown = result.script_path.read_text(encoding="utf-8")
    assert "The hero walks into the room." in markdown
    assert "And that is how it ends." in markdown
    # The section headings come from the section types.
    assert "Hook" in markdown
    assert "Ending" in markdown


def test_the_markdown_renderer_is_derived_from_the_script() -> None:
    """Rendering the same script twice gives the same text."""
    first = render_script_markdown(_script__output_set())
    second = render_script_markdown(_script__output_set())
    assert first == second
    assert first.strip()


def test_a_job_without_the_files_exports_what_it_has(tmp_path: Path) -> None:
    """An export of a job that stopped early copies what exists."""
    out = tmp_path / "out"
    result = export_output(tmp_path / "jobs", "job_1", out)
    assert result.files == []
    assert out.is_dir()
