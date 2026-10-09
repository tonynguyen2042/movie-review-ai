"""JSON bridge between the Electron desktop app and the Python pipeline (T111).

The desktop app must never re-implement anything the Python side already owns.
YAML parsing, settings validation and job queries all live here so there is one
implementation of each, in one language, covered by the existing pytest/ruff/mypy
gates. The Electron main process spawns this script and reads JSON from stdout.

Every subcommand prints exactly one JSON document on stdout and exits 0 on
success, 2 on a rejected request, so the caller never has to guess from a mix of
free text. Errors are reported as ``{"ok": false, "errors": [...]}`` rather than
a traceback, because a traceback in a GUI is a dead end for the user.

Usage::

    uv run python desktop/scripts/desktop_bridge.py settings:read
    uv run python desktop/scripts/desktop_bridge.py settings:write \\
        --target default --payload '{...}'
    uv run python desktop/scripts/desktop_bridge.py jobs:list --limit 50
    uv run python desktop/scripts/desktop_bridge.py jobs:show job_20261008_001
    uv run python desktop/scripts/desktop_bridge.py stages

Copyright: nothing here uploads, publishes or contacts a network service.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from movie_review.config.settings import (
    AppSettings,
    available_profiles,
    default_config_path,
    default_models_path,
    load_settings,
    read_yaml,
    repo_root,
)
from movie_review.pipeline.orchestrator import STAGE_SEQUENCE
from movie_review.ui.dashboard import JobDashboard

EXIT_OK = 0
EXIT_REJECTED = 2

#: Suffix for the temporary candidate files used to validate before a write. It
#: keeps the candidate inside the real config directory on purpose: that is the
#: only way ``default_models_path()`` resolves to the models.yaml the pipeline
#: will actually use.
_CANDIDATE_SUFFIX = ".desktop-validate"


def _emit(payload: dict[str, Any], code: int = EXIT_OK) -> int:
    """Print one JSON document and return the process exit code."""
    json.dump(payload, sys.stdout, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return code


def _fail(errors: list[str], code: int = EXIT_REJECTED) -> int:
    """Print a rejection payload."""
    return _emit({"ok": False, "errors": errors}, code)


def _backup_path(path: Path, when: datetime) -> Path:
    """Timestamped sibling path for a pre-write backup."""
    stamp = when.strftime("%Y%m%dT%H%M%S")
    return path.with_name(f"{path.name}.bak.{stamp}")


class _Candidate:
    """A candidate config/models file dropped beside the real one.

    Validation has to run against the real config directory, because the loader
    derives ``models.yaml`` from the directory of ``default.yaml``. Writing the
    candidate into a temp directory would silently validate it against a missing
    or wrong models.yaml, which is exactly the case the desktop app must catch.
    """

    def __init__(self, path: Path, payload: dict[str, Any]) -> None:
        self.real = path
        self.path = path.with_name(f"{path.stem}.{_CANDIDATE_SUFFIX}{path.suffix}")
        self._payload = payload

    def __enter__(self) -> Path:
        self.path.write_text(
            yaml.safe_dump(self._payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return self.path

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


def _validation_errors(config: Path, models: Path) -> list[str]:
    """Validate a candidate (config, models) pair, returning human-readable errors.

    Both files are validated together because the loader composes them: a
    ``models.profile`` in default.yaml only resolves if that profile exists in
    models.yaml, and every profile is expanded through ``ModelsSettings``. A pair
    that loads is the only definition of "valid" the pipeline itself has.
    """
    try:
        load_settings(config_path=config, models_path=models)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        return [f"{type(exc).__name__}: {exc}"]

    if config == default_config_path():
        # default.yaml selects a profile, so every profile the candidate models
        # file offers must also expand. A broken `remote` profile would otherwise
        # only fail once a user picked it, days later.
        errors: list[str] = []
        try:
            names = available_profiles(config_path=config, models_path=models)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            return [f"{type(exc).__name__}: {exc}"]
        for name in names:
            try:
                load_settings(config_path=config, models_path=models, profile=name)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
                errors.append(f"profile {name!r}: {type(exc).__name__}: {exc}")
        return errors
    return []


def _validate_target(target: str, payload: dict[str, Any]) -> tuple[Path, Path, list[str]]:
    """Return (config_path, models_path, errors) for a candidate payload.

    The candidate is written to a scratch path and validated as a pair with the
    untouched file, so an invalid edit can never be observed by the pipeline.
    """
    config = default_config_path()
    models = default_models_path(config)
    if target == "default":
        candidate = _Candidate(config, payload)
    elif target == "models":
        candidate = _Candidate(models, payload)
    else:
        raise ValueError(f"unknown target {target!r}; expected 'default' or 'models'")

    with candidate as candidate_path:
        if target == "default":
            pair = (candidate_path, models)
        else:
            pair = (config, candidate_path)
        return pair[0], pair[1], _validation_errors(*pair)


def _settings_read() -> dict[str, Any]:
    """Both config files as plain data, plus the profile catalog."""
    config = default_config_path()
    models = default_models_path(config)
    default_data = read_yaml(config)
    models_data = read_yaml(models)
    try:
        # The paths are passed explicitly rather than left to the loader's own
        # resolution: everything else in this script resolves them the same way,
        # and a read that silently validated a different file than the one the
        # app is about to edit would be worthless.
        settings: AppSettings = load_settings(config_path=config, models_path=models)
        loaded = settings.model_dump(mode="json")
        load_error: str | None = None
    except Exception as exc:  # noqa: BLE001 - shown in the UI, not raised
        loaded = {}
        load_error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": True,
        "paths": {
            "repo_root": str(repo_root()),
            "config": str(config),
            "models": str(models),
            "config_exists": config.is_file(),
            "models_exists": models.is_file(),
        },
        "default": default_data,
        "models": models_data,
        "profiles": available_profiles(config_path=config, models_path=models),
        "loaded": loaded,
        "load_error": load_error,
    }


def _settings_write(target: str, payload: dict[str, Any]) -> int:
    """Validate, back up, then overwrite a config file."""
    config = default_config_path()
    target_path = config if target == "default" else default_models_path(config)
    try:
        _, _, errors = _validate_target(target, payload)
    except ValueError as exc:
        return _fail([str(exc)])
    if errors:
        # Nothing is written: a file that fails to load would break every later
        # CLI invocation, including the one that is supposed to repair it.
        return _fail(errors)

    when = datetime.now(tz=UTC)
    backup = _backup_path(target_path, when)
    if target_path.is_file():
        shutil.copy2(target_path, backup)
    target_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return _emit(
        {
            "ok": True,
            "errors": [],
            "path": str(target_path),
            "backup": str(backup) if backup.exists() else None,
        }
    )


def _jobs_list(limit: int) -> int:
    """Job rows newest-first, as the dashboard reads them."""
    rows = JobDashboard().get_jobs()[:limit]
    return _emit({"ok": True, "jobs": rows})


def _jobs_show(job_id: str) -> int:
    """One job with its artifact rows, or a rejection when the ID is unknown."""
    details = JobDashboard().get_job_details(job_id)
    if details is None:
        return _fail([f"Unknown job id {job_id!r}"])
    return _emit({"ok": True, "job": details})


def _stages() -> int:
    """The pipeline stage sequence the desktop progress list is built from."""
    return _emit({"ok": True, "stages": [list(item) for item in STAGE_SEQUENCE]})


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for every subcommand."""
    parser = argparse.ArgumentParser(prog="desktop_bridge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("settings:read", help="Read both config files as JSON data.")
    sub.add_parser("stages", help="Print the pipeline stage sequence.")

    write = sub.add_parser("settings:write", help="Validate, back up and write a config file.")
    write.add_argument("--target", required=True, choices=["default", "models"])
    write.add_argument(
        "--payload",
        help="JSON object for the file. Reads stdin when omitted.",
    )
    write.add_argument(
        "--payload-file",
        help="Read the JSON payload from this file instead of argv. Config JSON "
        "is large enough and quote-heavy enough that passing it through a shell "
        "argument is a reliable way to corrupt it.",
    )

    listing = sub.add_parser("jobs:list", help="List jobs from the database.")
    listing.add_argument("--limit", type=int, default=100)

    show = sub.add_parser("jobs:show", help="Show one job and its artifacts.")
    show.add_argument("job_id")

    return parser


def _payload_text(args: argparse.Namespace) -> str:
    """Read the write payload from a file, an argument, or stdin.

    A file is preferred by the desktop app because JSON containing quotes and
    backslashes is easy to corrupt when it passes through a shell argument, and
    a silently corrupted config is worse than a refused one.
    """
    if getattr(args, "payload_file", None):
        # utf-8-sig: editors on Windows routinely add a BOM, and a BOM is not a
        # reason to reject an otherwise valid config payload.
        return Path(args.payload_file).read_text(encoding="utf-8-sig")
    payload: str | None = getattr(args, "payload", None)
    if payload:
        return payload
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "settings:read":
            return _emit(_settings_read())
        if args.command == "stages":
            return _stages()
        if args.command == "settings:write":
            payload = json.loads(_payload_text(args))
            if not isinstance(payload, dict):
                return _fail(["Payload must be a JSON object."])
            return _settings_write(args.target, payload)
        if args.command == "jobs:list":
            return _jobs_list(max(1, args.limit))
        if args.command == "jobs:show":
            return _jobs_show(args.job_id)
    except json.JSONDecodeError as exc:
        return _fail([f"Payload is not valid JSON: {exc}"])
    except Exception as exc:  # noqa: BLE001 - a GUI must not show a traceback
        return _fail([f"{type(exc).__name__}: {exc}"])
    return _fail([f"Unhandled command {args.command!r}"])


if __name__ == "__main__":
    raise SystemExit(main())
