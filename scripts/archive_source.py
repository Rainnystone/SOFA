#!/usr/bin/env python3
"""SOFA workspace source cache mutation CLI (main thread only).

The only supported mutation path for sources/ and sources_index.jsonl.
Append-only: adds never overwrite an excerpt or rewrite the index; identical
content (newline-normalized sha256) dedupes to the existing source id. There
are no edit or remove subcommands - a wrong record is superseded by archiving
a corrected source.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_cache import (  # noqa: E402
    GRADES,
    SourceCacheError,
    add_source,
    evaluate_index,
    load_index,
    render_source_bibliography,
)


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SourceCacheError(message)


def command_add(workspace: Path, args: argparse.Namespace) -> int:
    excerpt_text = Path(args.excerpt_file).read_text(encoding="utf-8")
    result = add_source(
        workspace,
        url=args.url,
        title=args.title,
        retrieved=args.retrieved,
        grade=args.grade,
        excerpt_text=excerpt_text,
    )
    if result.created:
        print(f"已归档: {result.source_id}")
        if result.url_duplicates:
            print(
                f"提示: 该 URL 已有记录 {', '.join(result.url_duplicates)}"
                "（同一文档的不同摘录）"
            )
    else:
        print(f"内容已存在，未新增: {result.source_id}")
    return 0


def command_status(workspace: Path, args: argparse.Namespace) -> int:
    # load_index raises SourceCacheError on an unparseable index (loud, exit
    # 1 via main); evaluate_index then collects record-level issues, which
    # status reports while still exiting 0 - readiness authority stays with
    # sofa_contract alone.
    load_index(workspace)
    evaluation = evaluate_index(workspace)
    if args.json:
        print(
            json.dumps(
                {
                    "records": len(evaluation.records),
                    "issues": [asdict(issue) for issue in evaluation.issues],
                    "warnings": [asdict(warning) for warning in evaluation.warnings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(f"已归档来源: {len(evaluation.records)}")
    grade_counts: dict[str, int] = {}
    for record in evaluation.records:
        grade_counts[record["grade"]] = grade_counts.get(record["grade"], 0) + 1
    for grade in GRADES:
        if grade in grade_counts:
            print(f"- Grade {grade}: {grade_counts[grade]}")
    for issue in evaluation.issues:
        print(f"- {issue.code}: {issue.location}: {issue.message}")
    for warning in evaluation.warnings:
        print(f"- [WARN] {warning.code}: {warning.location}: {warning.message}")
    return 0


def command_bibliography(workspace: Path, _args: argparse.Namespace) -> int:
    text = render_source_bibliography(workspace)
    if text:
        print(text, end="")
    else:
        print("（无已归档来源）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(
        description="Mutate and inspect the SOFA workspace source cache (append-only)."
    )
    parser.add_argument("workspace", help="SOFA workspace directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Archive one deep-read excerpt")
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--retrieved", required=True, help="YYYY-MM-DD")
    add_parser.add_argument(
        "--grade", required=True, help="A|B|C|D (recorded, never interpreted)"
    )
    add_parser.add_argument("--excerpt-file", required=True, dest="excerpt_file")
    add_parser.set_defaults(func=command_add)

    status_parser = subparsers.add_parser(
        "status", help="Show record counts and validation findings"
    )
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=command_status)

    subparsers.add_parser(
        "bibliography", help="Print the identifiers-only bibliographic index"
    ).set_defaults(func=command_bibliography)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        workspace = Path(args.workspace)
        return args.func(workspace, args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
