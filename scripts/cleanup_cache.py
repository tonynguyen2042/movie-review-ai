#!/usr/bin/env python
"""Reclaim the disk: prune the cache and drop the regenerable intermediates.

README section 84 puts the raw frames, the temporary clips, the proxy video
and the temporary audio in the "optional cleanup" list. A feature-length run
leaves hundreds of megabytes of JPEG frames behind, and the cache grows
without bound.

Nothing here removes an artifact of record. The frames' manifest, the
transcript, the analysis, the script and the render all stay; the frames
themselves are regenerable from the movie.

    python scripts/cleanup_cache.py
    python scripts/cleanup_cache.py --older-than 7d --frames
    python scripts/cleanup_cache.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# The package lives under ``src/``, so a checkout works without an install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from movie_review.cache.manager import CacheManager  # noqa: E402
from movie_review.config.settings import load_settings, set_config_path  # noqa: E402

#: How the ``--older-than`` value is read: ``30m``, ``2h``, ``7d`` or a
#: number of seconds.
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _seconds(value: str) -> float:
    """Parse ``30m``, ``2h``, ``7d`` or a plain number of seconds."""
    text = value.strip().lower()
    if text and text[-1] in _UNITS:
        try:
            return float(text[:-1]) * _UNITS[text[-1]]
        except ValueError as exc:
            raise ValueError(f"Cannot read {value!r} as an age") from exc
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Cannot read {value!r} as an age") from exc


def _prune_cache(cache_dir: Path, older_than: float | None, dry_run: bool) -> list[str]:
    """Remove the cache entries that are old enough."""
    cache = CacheManager(cache_dir)
    if dry_run:
        removed: list[str] = []
        for meta in sorted(cache_dir.glob("*.meta.json")):
            key = meta.name[: -len(".meta.json")]
            if older_than is not None and time.time() - meta.stat().st_mtime < older_than:
                continue
            removed.append(key)
        return removed
    return cache.prune(older_than_seconds=older_than)


def _drop_frames(jobs_dir: Path, dry_run: bool) -> list[str]:
    """Drop the frame images every job has finished with."""
    from movie_review.pipeline.cleanup import cleanup_intermediates

    removed: list[str] = []
    if not jobs_dir.is_dir():
        return removed
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        if dry_run:
            frames = job_dir / "frames"
            if frames.is_dir():
                removed.extend(
                    str(path.relative_to(jobs_dir)) for path in sorted(frames.rglob("*.jpg"))
                )
            continue
        for path in cleanup_intermediates(job_dir):
            removed.append(str(path.relative_to(jobs_dir)))
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--older-than",
        help="Only remove entries older than this: 30m, 2h, 7d or seconds.",
    )
    parser.add_argument(
        "--frames",
        action="store_true",
        help="Also drop the sampled frames of every job.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed, and remove nothing.",
    )
    parser.add_argument("--profile", help="The configuration profile to read.")
    parser.add_argument("--config", help="Config file to use (default: <repo>/config/config.yaml).")
    args = parser.parse_args(argv)
    set_config_path(args.config)

    try:
        older_than = _seconds(args.older_than) if args.older_than else None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    settings = load_settings(profile=args.profile)
    data_dir = Path(settings.paths.data_dir)

    removed_cache = _prune_cache(data_dir / "cache", older_than, args.dry_run)
    removed_frames: list[str] = []
    if args.frames:
        removed_frames = _drop_frames(data_dir / "jobs", args.dry_run)

    report = {
        "dry_run": args.dry_run,
        "cache_dir": str(data_dir / "cache"),
        "cache_entries_removed": len(removed_cache),
        "frames_removed": len(removed_frames),
        "cache_keys": removed_cache[:50],
        "frame_paths": removed_frames[:50],
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
