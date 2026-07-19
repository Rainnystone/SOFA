#!/usr/bin/env python3
"""Cross-platform coverage runner for locked SOFA coverage targets.

Replaces the bash-only ``run_coverage.sh`` so Windows users can run the
lifecycle coverage gate without a POSIX shell. Everything is invoked through
``sys.executable`` so the same interpreter that runs this script also runs
coverage and the tests.

Usage:
    python scripts/run_coverage.py
    python scripts/run_coverage.py --fail-under 90
    python scripts/run_coverage.py --target revisit --fail-under 90

Exit code is non-zero when the measured coverage is below ``--fail-under``
(mirrors the old ``run_coverage.sh`` semantics).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Resolve the repo root from this file's location so the script works from any
# working directory on any OS (no hard-coded temporary-directory or absolute paths).
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAIL_UNDER = 90
COVERAGE_SOURCE = "scripts"
COVERAGE_TARGETS = {
    "frontier": {
        "tests": ("tests/test_frontier_lifecycle.py",),
        "include": "scripts/frontier_lifecycle.py",
    },
    "revisit": {
        "tests": ("tests/test_revisit_contract.py",),
        "include": "scripts/revisit_contract/*.py,scripts/revisit_cycle.py",
    },
}


def build_argv(
    fail_under: int,
    target: str = "frontier",
) -> list[list[str]]:
    """Return the two argv lists (run, report) for the coverage commands."""
    selected = COVERAGE_TARGETS[target]
    run_args = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--source",
        COVERAGE_SOURCE,
        "-m",
        "unittest",
        *selected["tests"],
    ]
    report_args = [
        sys.executable,
        "-m",
        "coverage",
        "report",
        "--include",
        selected["include"],
        "--fail-under",
        str(fail_under),
    ]
    return [run_args, report_args]


def main(
    fail_under: int = DEFAULT_FAIL_UNDER,
    target: str = "frontier",
) -> int:
    run_args, report_args = build_argv(fail_under, target=target)
    # Run from the repo root so relative test/source paths resolve identically
    # across platforms.
    run = subprocess.run(run_args, cwd=ROOT)
    if run.returncode != 0:
        return run.returncode
    report = subprocess.run(report_args, cwd=ROOT)
    return report.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a locked SOFA coverage gate (cross-platform).",
    )
    parser.add_argument(
        "--target",
        choices=tuple(COVERAGE_TARGETS),
        default="frontier",
        help="Coverage target to measure (default: frontier).",
    )
    parser.add_argument(
        "--fail-under",
        type=int,
        default=DEFAULT_FAIL_UNDER,
        help=f"Minimum coverage percent required (default: {DEFAULT_FAIL_UNDER}).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(fail_under=args.fail_under, target=args.target))
