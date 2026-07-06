#!/usr/bin/env python3
"""Assemble a complete SOFA worker dispatch from catalog facts.

Deterministic composition only: fills declared slots in the curated prompt
template, computes the canonical delivery path, screens the input against
role forbidden-input tripwires, and attaches the prior-query digest when
available. Read-only: never writes workspace files, never appends to
dispatch_log.jsonl, never dispatches.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dispatch_assembly import (
    AssemblyError,
    assemble_dispatch,
    primary_input_slot_name,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_FIELD_ARGS = ("loop", "frontier_slug", "round", "ticker", "version")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a SOFA worker dispatch (composition only; read-only)."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--role", required=True, help="Role slug or dispatch alias, e.g. scout")
    parser.add_argument(
        "--packet-file", required=True,
        help="File whose content fills the role's primary input slot",
    )
    parser.add_argument("--loop", default=None)
    parser.add_argument("--frontier-slug", dest="frontier_slug", default=None)
    parser.add_argument("--round", dest="round", default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--version", default=None)
    parser.add_argument("--out", default=None, help="Override the workspace-relative delivery path")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-digest", action="store_true")
    args = parser.parse_args(argv)

    try:
        with open(args.packet_file, "r", encoding="utf-8") as handle:
            input_text = handle.read()
        name_fields = {
            key: getattr(args, key)
            for key in NAME_FIELD_ARGS
            if getattr(args, key) is not None
        }
        input_slot = primary_input_slot_name(args.role)
        result = assemble_dispatch(
            repo_root=REPO_ROOT,
            workspace=args.workspace,
            role=args.role,
            slot_values={input_slot: input_text},
            name_fields=name_fields,
            attach_digest=not args.no_digest,
            out_path=args.out,
        )
    except (AssemblyError, OSError, ValueError) as exc:
        print(f"ASSEMBLY ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = dataclasses.asdict(result)
        payload.pop("delivery_abs_path", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result.dispatch_text, end="")
        print(f"DELIVERY PATH: {result.delivery_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
