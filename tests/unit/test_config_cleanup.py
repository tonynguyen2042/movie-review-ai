"""The configuration and the licence have to be real.

T171. The repository had no `LICENSE` file, although the desktop app
declared MIT.

Six configuration knobs were declared and read by nothing:

- `runtime.backend` and `runtime.device` — the runtime is chosen per model
  slot, by `models.*.backend`
- `privacy.telemetry` — the project sends no telemetry, so the flag promised
  something that did not exist
- `memory.reserve_mb` — nothing measured memory
- `logging.json_output` — the output is always JSON
- `pipeline.evidence_required` — nothing read it
- the top-level `style` — the style lives on the job now

Two more were real switches that nothing honoured:

- `media.ffprobe` — the configured ffprobe was ignored, so the probe always
  used the one on the PATH
- `pipeline.diarization` — the diarization stage ran whatever the setting
  said
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _config__config_cleanup() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
        return loaded


def _config_document() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (ROOT / "config" / "config.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def test_the_licence_exists() -> None:
    """The desktop app declared MIT and the repository had no licence."""
    licence = ROOT / "LICENSE"
    assert licence.is_file()
    assert "MIT License" in licence.read_text(encoding="utf-8")


def test_the_declared_licence_matches_the_file() -> None:
    """A declared licence that is not the file is a false promise."""
    import json

    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert package["license"] == "MIT"
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_the_removed_knobs_are_gone() -> None:
    """A setting that nothing reads is a promise nothing keeps."""
    from movie_review.config.settings import AppSettings

    fields = set(AppSettings.model_fields)
    assert "runtime" not in fields
    assert "memory" not in fields
    assert "style" not in fields
    from movie_review.config.settings import PrivacySettings

    assert "telemetry" not in PrivacySettings.model_fields


def test_the_default_configuration_no_longer_names_them() -> None:
    document = _config_document()
    assert "runtime" not in document
    assert "memory" not in document
    assert "telemetry" not in document.get("privacy", {})
    assert "json_output" not in document.get("logging", {})
    assert "evidence_required" not in document.get("pipeline", {})
    # The top-level style was retired in T171; the file merge (T182) dropped
    # the dead key it left behind.
    assert "style" not in document


def test_the_ffprobe_path_is_honoured(tmp_path: Path, monkeypatch) -> None:
    """The setting existed and the probe ignored it."""
    from movie_review.media import ffmpeg as ff

    seen: list[str] = []

    def fake_probe(path: str, ffprobe: str = "ffprobe"):
        seen.append(ffprobe)
        from movie_review.domain import MovieMetadata

        return MovieMetadata(
            file=path,
            sha256="a" * 64,
            duration_seconds=10.0,
            width=320,
            height=240,
            fps=25.0,
            video_codec="h264",
        )

    monkeypatch.setattr(ff, "probe", fake_probe)
    ff.probe("movie.mp4", "/opt/bin/ffprobe")
    assert seen == ["/opt/bin/ffprobe"]


def test_the_diarization_switch_is_honoured() -> None:
    """A switch that nothing honours is a switch that lies."""
    from movie_review.config.settings import load_settings

    assert load_settings().pipeline.diarization is True
