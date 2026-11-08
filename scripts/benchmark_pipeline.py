#!/usr/bin/env python
"""Measure the whole pipeline on a reference movie, stage by stage.

README section 76 says the pipeline benchmark runs on a short reference
movie -- ten to fifteen minutes -- and reports the time each stage took.

The measurement itself lives in ``movie_review.benchmark``; this script is
the thin wrapper that the repository structure promises.

    python scripts/benchmark_pipeline.py --movie ./reference.mkv
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
    run_pipeline_benchmark,
)
from movie_review.config.settings import load_settings, set_config_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--movie", required=True, help="The reference movie.")
    parser.add_argument("--db-path", help="Where the job database lives.")
    parser.add_argument("--profile", help="The model profile to measure.")
    parser.add_argument("--config", help="Config file to use (default: <repo>/config/config.yaml).")
    args = parser.parse_args(argv)
    set_config_path(args.config)

    settings = load_settings(profile=args.profile)

    try:
        report = run_pipeline_benchmark(args.movie, args.db_path, settings)
    except BenchmarkError as exc:
        print(f"Cannot run the benchmark: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
