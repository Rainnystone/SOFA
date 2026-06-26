from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def read_text_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} JSON file must be an object")
    return value


def iter_jsonl_records(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} JSONL record must be an object")
        yield line_number, value
