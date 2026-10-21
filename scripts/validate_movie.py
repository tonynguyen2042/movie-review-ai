#!/usr/bin/env python
"""Check that a movie is usable, or that a job's artifacts are intact.

Two things are worth checking before a long run and after one:

- a movie file: does ffprobe read it, and what does it say about it
- a job: is every artifact it recorded still present and unmodified

The checks themselves live in ``movie_review``; this script is the thin
wrapper that the repository structure promises.

    python scripts/validate_movie.py ./my-movie.mkv
    python scripts/validate_movie.py --job job_20261006_001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# The package lives under ``src/``, so a checkout works without an install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from movie_review.config.settings import load_settings  # noqa: E402


def _validate_movie(movie: Path, ffprobe: str) -> tuple[dict[str, Any], bool]:
    """Read a movie's media metadata; the check is that ffprobe reads it."""
    from movie_review.media.ffmpeg import probe

    metadata = probe(str(movie), ffprobe)
    document = metadata.model_dump(mode="json")
    document["file"] = str(movie)
    return document, True


def _validate_job(job_id: str, db_path: str | None) -> tuple[dict[str, Any], bool]:
    """Check that every artifact a job recorded is present and unmodified."""
    from movie_review.pipeline.orchestrator import validate_job

    report = validate_job(job_id, db_path)
    document = {
        "job_id": report.job_id,
        "checked": report.checked,
        "ok": report.ok,
        "missing": report.missing,
        "corrupt": report.corrupt,
        "unsafe": report.unsafe,
        "unlocated": report.unlocated,
        "passed": report.passed,
    }
    return document, report.passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "movie",
        nargs="?",
        help="The movie file to read. Omit it when validating a job.",
    )
    parser.add_argument("--job", help="The job whose artifacts to check.")
    parser.add_argument("--db-path", help="Where the job database lives.")
    parser.add_argument("--profile", help="The configuration profile to read.")
    args = parser.parse_args(argv)

    if not args.movie and not args.job:
        parser.error("give a movie file or --job")
    if args.movie and args.job:
        parser.error("give a movie file or --job, not both")

    settings = load_settings(profile=args.profile)

    if args.job:
        document, passed = _validate_job(args.job, args.db_path)
    else:
        path = Path(args.movie)
        if not path.is_file():
            print(f"Input file not found: {path}", file=sys.stderr)
            return 1
        try:
            document, passed = _validate_movie(path, settings.media.ffprobe)
        except Exception as exc:  # a file ffprobe cannot read is the answer
            print(f"Cannot read {path}: {exc}", file=sys.stderr)
            return 1

    print(json.dumps(document, indent=2, sort_keys=True, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
