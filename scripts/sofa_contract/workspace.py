from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from workspace_contract import all_worker_output_directories, is_main_thread_artifact


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


def find_worker_outputs(workspace_path: Path) -> list[Path]:
    outputs: list[Path] = []
    for dirname in all_worker_output_directories():
        directory = workspace_path / dirname
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix != ".md" or not path.is_file():
                continue
            relative_path = path.relative_to(workspace_path).as_posix()
            if is_main_thread_artifact(relative_path):
                continue
            outputs.append(path)
    return outputs


def markdown_table_has_data_row(text: str | None) -> bool:
    if not text:
        return False
    after_separator = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            after_separator = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if _is_markdown_table_separator(cells):
            after_separator = True
            continue
        if after_separator and any(cells):
            return True
    return False


def _is_markdown_table_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":"} and "-" in cell for cell in cells)


def parse_stage_progress(workflow_text: str | None) -> dict[str, str]:
    if not workflow_text:
        return {}
    statuses: dict[str, str] = {}
    for line in workflow_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| Stage "):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        stage_cell = cells[0].lower()
        status = cells[1].lower()
        for index in range(0, 7):
            if f"stage {index}" in stage_cell:
                statuses[f"stage_{index}"] = status
    return statuses


def find_markdown_reports(workspace_path: Path) -> list[Path]:
    reports_dir = workspace_path / "reports"
    if not reports_dir.exists():
        return []
    return sorted(path for path in reports_dir.iterdir() if path.suffix == ".md")
