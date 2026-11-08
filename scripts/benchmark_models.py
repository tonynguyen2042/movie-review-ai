#!/usr/bin/env python
"""Measure one model slot: load time, throughput and peak memory.

README section 75 lists the measurements, and section 56 says the exact
model sizes "SHALL be benchmarked on the target Mac rather than
hard-coded" -- which needs a command that takes the measurements.

The measurement itself lives in ``movie_review.benchmark``; this script is
the thin wrapper that the repository structure promises.

    python scripts/benchmark_models.py --slot reasoning
    python scripts/benchmark_models.py --slot vision --movie ./reference.mkv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The package lives under ``src/``, so a checkout works without an install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from movie_review.benchmark.runner import (  # noqa: E402
    BenchmarkError,
    run_model_benchmark,
)
from movie_review.config.settings import load_settings, set_config_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--slot",
        required=True,
        choices=("reasoning", "tts", "asr", "vision"),
        help="Which model slot to measure.",
    )
    parser.add_argument(
        "--movie",
        help="A movie to take a frame from. The vision slot needs one.",
    )
    parser.add_argument(
        "--repeats", type=int, default=3, help="How many times to repeat the measurement."
    )
    parser.add_argument("--profile", help="The model profile to measure.")
    parser.add_argument("--config", help="Config file to use (default: <repo>/config/config.yaml).")
    parser.add_argument(
        "--workdir",
        help="Where the probe files are written. Defaults to the data directory.",
    )
    args = parser.parse_args(argv)
    set_config_path(args.config)

    settings = load_settings(profile=args.profile)
    workdir = Path(args.workdir) if args.workdir else Path(settings.paths.data_dir) / "benchmark"

    try:
        report = run_model_benchmark(
            settings,
            args.slot,
            workdir,
            repeats=args.repeats,
            movie=args.movie,
        )
    except BenchmarkError as exc:
        print(f"Cannot run the benchmark: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
