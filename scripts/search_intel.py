#!/usr/bin/env python3
"""Render prior-query digests and advisory search yield stats; negative trace only."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from capability_policy import (  # noqa: E402
    build_prior_query_digest,
    build_search_yield_stats,
    render_prior_query_digest,
    render_search_yield_stats,
)


class SearchIntelArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    parser = SearchIntelArgumentParser(
        description="Render SOFA search-record intelligence views"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    digest_parser = subparsers.add_parser(
        "digest",
        help="Render the prior-query digest",
    )
    digest_parser.add_argument("workspace")
    digest_parser.add_argument("--frontier")
    digest_parser.add_argument("--json", action="store_true")

    stats_parser = subparsers.add_parser(
        "stats",
        help="Render advisory search yield statistics",
    )
    stats_parser.add_argument("workspace")
    stats_parser.add_argument("--loop")
    stats_parser.add_argument("--json", action="store_true")

    try:
        args = parser.parse_args(argv)

        if args.command == "digest":
            groups = build_prior_query_digest(args.workspace)
            if args.frontier:
                groups = [group for group in groups if group.group_id == args.frontier]
            if args.json:
                print(
                    json.dumps(
                        [dataclasses.asdict(group) for group in groups],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(render_prior_query_digest(groups), end="")
            return 0

        stats = build_search_yield_stats(args.workspace)
        loop_filter = _normalize_loop_filter(args.loop)
        if loop_filter:
            stats = [entry for entry in stats if entry.loop_key == loop_filter]
        if args.json:
            print(
                json.dumps(
                    [dataclasses.asdict(entry) for entry in stats],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(render_search_yield_stats(stats), end="")
        return 0
    except (OSError, ValueError) as exc:
        print(f"SEARCH INTEL ERROR: {exc}", file=sys.stderr)
        return 1


def _normalize_loop_filter(loop: str | None) -> str | None:
    if loop is None:
        return None
    if loop.isdecimal():
        return f"loop_{int(loop)}"
    return loop


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
