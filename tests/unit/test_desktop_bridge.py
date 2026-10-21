"""Tests for the Electron desktop app's Python bridge (T111).

The bridge is loaded by path rather than imported as a package: it is a script
that Electron spawns, not a module in ``src/movie_review``. It is still covered
here because it is the only place the desktop app validates configuration, and a
silently accepted bad config would break every later CLI invocation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

_BRIDGE_PATH = Path(__file__).resolve().parents[2] / "desktop" / "scripts" / "desktop_bridge.py"


def _load_bridge() -> ModuleType:
    """Import ``desktop_bridge.py`` by path, once per session."""
    if "desktop_bridge" in sys.modules:
        return sys.modules["desktop_bridge"]
    spec = importlib.util.spec_from_file_location("desktop_bridge", _BRIDGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["desktop_bridge"] = module
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


def _valid_models() -> dict[str, Any]:
    """A minimal models.yaml that loads for every profile it declares."""
    slots: dict[str, Any] = {
        "asr": {"model": "whisper-large-v3-turbo", "precision": "fp16"},
        "vision": {"model": "Qwen3-VL", "precision": "4bit"},
        "reasoning": {"model": "Qwen3.5-27B", "precision": "4bit"},
        "critic": {"model": "Qwen3.5-27B", "precision": "4bit", "enabled": False},
        "tts": {"model": "Qwen3-TTS-12Hz-1.7B", "precision": "8bit"},
    }
    return {"profiles": {"balanced": dict(slots)}}


def _valid_default() -> dict[str, Any]:
    """A minimal default.yaml that loads against :func:`_valid_models`.

    ``models`` and ``prompts`` are the only required sections; everything else has
    a code fallback. A test fixture that omits them would fail validation for the
    wrong reason and prove nothing about the bridge.
    """
    return {
        "models": {"profile": "balanced"},
        "prompts": {"versions": {"scene_analysis": "v1", "script_writer": "v1"}},
        "paths": {"data_dir": "data"},
    }


def _config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bridge at a throwaway config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    default = config_dir / "default.yaml"
    models = config_dir / "models.yaml"
    default.write_text(yaml.safe_dump(_valid_default()), encoding="utf-8")
    models.write_text(yaml.safe_dump(_valid_models()), encoding="utf-8")
    monkeypatch.setattr(bridge, "default_config_path", lambda: default)
    monkeypatch.setattr(bridge, "default_models_path", lambda _config: models)
    return config_dir


def _write_payload(tmp_path: Path, payload: Any, encoding: str = "utf-8") -> str:
    """Write a JSON payload to disk and return its path."""
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding=encoding)
    return str(path)


class _StubDashboard:
    """Stand-in for :class:`JobDashboard` so tests need no database."""

    rows: list[dict[str, Any]] = []
    details: dict[str, Any] | None = None

    def __init__(self, host: str = "", port: int = 0, db_path: str | None = None) -> None:
        self.host = host
        self.port = port
        self.db_path = db_path

    def get_jobs(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def get_job_details(self, job_id: str) -> dict[str, Any] | None:
        if self.details is None or self.details.get("job_id") != job_id:
            return None
        return self.details


def test_stages_reports_the_full_pipeline_sequence(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.loads(_call(bridge._stages, capsys))

    assert payload["ok"] is True
    assert [name for name, _title in payload["stages"]] == [
        "ingest",
        "scenes",
        "transcript",
        "vision",
        "characters",
        "locations",
        "events",
        "arcs",
        "themes",
        "twists",
        "story",
        "review",
        "verify",
        "review-translate",
        "tts-chunks",
        "tts-concat",
        "tts-reconcile",
        "render-manifest",
        "subtitles",
        "render",
        "quality",
    ]


def test_stages_titles_are_not_empty(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.loads(_call(bridge._stages, capsys))

    assert all(title.strip() for _name, title in payload["stages"])


def test_settings_read_returns_both_files_and_the_profile_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir(tmp_path, monkeypatch)

    payload = bridge._settings_read()

    assert payload["ok"] is True
    assert payload["profiles"] == ["balanced"]
    assert payload["paths"]["config"].endswith("default.yaml")
    assert payload["default"]["models"]["profile"] == "balanced"
    assert payload["load_error"] is None


def test_settings_read_reports_a_broken_config_instead_of_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)
    broken = {**_valid_default(), "pipeline": {"review": {"target_wpm": -5}}}
    (config_dir / "default.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")

    payload = bridge._settings_read()

    assert payload["load_error"] is not None
    assert "target_wpm" in payload["load_error"]
    assert payload["loaded"] == {}


def test_write_creates_a_timestamped_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)
    original = (config_dir / "default.yaml").read_text(encoding="utf-8")

    code = bridge.main(
        [
            "settings:write",
            "--target",
            "default",
            "--payload-file",
            _write_payload(tmp_path, _valid_default()),
        ]
    )

    payload = json.loads(_stdout(capsys))
    assert code == 0
    assert payload["ok"] is True
    backups = list(config_dir.glob("default.yaml.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original


def test_write_applies_the_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)

    code = bridge.main(
        [
            "settings:write",
            "--target",
            "models",
            "--payload-file",
            _write_payload(
                tmp_path,
                {
                    "profiles": {
                        "balanced": {
                            **_valid_models()["profiles"]["balanced"],
                            "reasoning": {"model": "Qwen3.5-9B", "precision": "4bit"},
                        }
                    }
                },
            ),
        ]
    )

    written = yaml.safe_load((config_dir / "models.yaml").read_text(encoding="utf-8"))
    assert code == 0
    assert written["profiles"]["balanced"]["reasoning"]["model"] == "Qwen3.5-9B"


def test_write_rejects_an_unknown_profile_and_leaves_the_file_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)
    before = (config_dir / "models.yaml").read_text(encoding="utf-8")

    code = bridge.main(
        [
            "settings:write",
            "--target",
            "models",
            "--payload",
            json.dumps({"profiles": {}}),
        ]
    )

    payload = json.loads(_stdout(capsys))
    assert code == 2
    assert payload["ok"] is False
    assert payload["errors"]
    assert (config_dir / "models.yaml").read_text(encoding="utf-8") == before
    assert not list(config_dir.glob("*.bak.*"))


def test_write_rejects_a_remote_slot_without_a_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir(tmp_path, monkeypatch)
    slots = _valid_models()["profiles"]["balanced"]
    broken = {**slots, "vision": {"model": "Qwen3-VL", "backend": "openai_compatible"}}

    code = bridge.main(
        [
            "settings:write",
            "--target",
            "models",
            "--payload",
            json.dumps({"profiles": {"balanced": broken}}),
        ]
    )

    payload = json.loads(_stdout(capsys))
    assert code == 2
    assert payload["ok"] is False
    assert "base_url" in json.dumps(payload)


def test_write_rejects_a_profile_that_is_not_the_active_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broken secondary profile must not wait days to be discovered."""
    _config_dir(tmp_path, monkeypatch)
    slots = _valid_models()["profiles"]["balanced"]
    broken = {"quality": {**slots, "tts": {"model": "x", "backend": "not-a-backend"}}}

    code = bridge.main(
        [
            "settings:write",
            "--target",
            "models",
            "--payload",
            json.dumps({"profiles": {"balanced": dict(slots), **broken}}),
        ]
    )

    payload = json.loads(_stdout(capsys))
    assert code == 2
    assert "quality" in json.dumps(payload)


def test_write_leaves_no_candidate_file_behind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = _config_dir(tmp_path, monkeypatch)

    bridge.main(["settings:write", "--target", "default", "--payload", json.dumps({})])

    assert not list(config_dir.glob("*desktop-validate*"))


def test_write_accepts_a_payload_file_with_a_bom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir(tmp_path, monkeypatch)
    path = tmp_path / "bom.json"
    path.write_text(json.dumps(_valid_default()), encoding="utf-8-sig")

    code = bridge.main(["settings:write", "--target", "default", "--payload-file", str(path)])

    assert code == 0
    assert json.loads(_stdout(capsys))["ok"] is True


def test_write_rejects_malformed_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir(tmp_path, monkeypatch)
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    code = bridge.main(["settings:write", "--target", "default", "--payload-file", str(path)])

    assert code == 2
    assert json.loads(_stdout(capsys))["ok"] is False


def test_write_rejects_a_json_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir(tmp_path, monkeypatch)

    code = bridge.main(["settings:write", "--target", "default", "--payload", "[1, 2]"])

    assert code == 2
    assert "JSON object" in json.dumps(json.loads(_stdout(capsys)))


def test_jobs_list_passes_the_limit_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _StubDashboard.rows = [{"job_id": f"job_{n}"} for n in range(5)]
    monkeypatch.setattr(bridge, "JobDashboard", _StubDashboard)

    code = bridge.main(["jobs:list", "--limit", "2"])
    payload = json.loads(_stdout(capsys))

    assert code == 0
    assert [row["job_id"] for row in payload["jobs"]] == ["job_0", "job_1"]


def test_jobs_show_rejects_an_unknown_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _StubDashboard.details = None
    monkeypatch.setattr(bridge, "JobDashboard", _StubDashboard)

    code = bridge.main(["jobs:show", "job_missing"])

    assert code == 2
    assert "job_missing" in json.dumps(json.loads(_stdout(capsys)))


def test_jobs_show_returns_the_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _StubDashboard.details = {"job_id": "job_1", "status": "COMPLETED"}
    monkeypatch.setattr(bridge, "JobDashboard", _StubDashboard)

    code = bridge.main(["jobs:show", "job_1"])
    payload = json.loads(_stdout(capsys))

    assert code == 0
    assert payload["job"]["status"] == "COMPLETED"


def test_main_rejects_an_unknown_command() -> None:
    with pytest.raises(SystemExit):
        bridge.main(["nonsense"])


def _call(fn: Any, capsys: pytest.CaptureFixture[str]) -> str:
    """Run a bridge entry point and return the JSON it printed."""
    fn()
    return _stdout(capsys)


def _stdout(capsys: pytest.CaptureFixture[str]) -> str:
    """Everything the bridge wrote to stdout during the current test."""
    return capsys.readouterr().out
