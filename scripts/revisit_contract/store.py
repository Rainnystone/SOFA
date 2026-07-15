from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Any

from .model import (
    CYCLES_DIRNAME,
    CYCLE_ID_RE,
    POINTER_FILENAME,
    RevisitContractError,
    validate_cycle,
    validate_pointer,
)
from .render import render_cycle_markdown


class RevisitPersistenceRollbackError(RevisitContractError):
    def __init__(self, original_error: Exception, rollback_error: Exception) -> None:
        self.original_error = original_error
        self.rollback_error = rollback_error
        super().__init__(
            "cycle persistence failed "
            f"({type(original_error).__name__}: {original_error}); "
            "mirror rollback failed "
            f"({type(rollback_error).__name__}: {rollback_error})"
        )


def canonical_value_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_document_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_workspace_relative_path(value: str | Path) -> str:
    raw = str(value)
    if not raw or any(unicodedata.category(char) == "Cc" for char in raw):
        raise RevisitContractError(
            "workspace-relative path must be non-empty and control-free"
        )
    windows = PureWindowsPath(raw)
    if Path(raw).is_absolute() or windows.drive or windows.root:
        raise RevisitContractError(f"absolute workspace path is forbidden: {raw!r}")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise RevisitContractError(
            f"workspace path contains forbidden '..': {raw!r}"
        )
    normalized = "/".join(part for part in parts if part not in {"", "."})
    if not normalized:
        raise RevisitContractError("workspace-relative path resolves to empty")
    return normalized


def resolve_workspace_path(
    workspace: str | Path,
    value: str | Path,
    *,
    parent: str | None = None,
    suffix: str | None = None,
) -> Path:
    root = Path(workspace).resolve()
    relative = normalize_workspace_relative_path(value)
    if parent is not None and not relative.startswith(f"{parent.rstrip('/')}/"):
        raise RevisitContractError(f"path must be under {parent}/: {relative}")
    if suffix is not None and Path(relative).suffix != suffix:
        raise RevisitContractError(f"path must end with {suffix}: {relative}")
    resolved = (root / relative).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RevisitContractError(f"path escapes workspace: {relative}") from exc
    if parent is not None:
        unresolved_parent = root / parent.rstrip("/")
        try:
            resolved.relative_to(unresolved_parent)
        except ValueError as exc:
            raise RevisitContractError(
                f"resolved path must be under {parent}/: {relative}"
            ) from exc
    if suffix is not None and resolved.suffix != suffix:
        raise RevisitContractError(
            f"resolved path must end with {suffix}: {relative}"
        )
    return resolved


def pointer_path(workspace: str | Path) -> Path:
    return resolve_workspace_path(workspace, POINTER_FILENAME, suffix=".json")


def cycle_directory(workspace: str | Path) -> Path:
    return resolve_workspace_path(workspace, CYCLES_DIRNAME)


def _require_cycle_id(cycle_id: str) -> str:
    if not isinstance(cycle_id, str) or CYCLE_ID_RE.fullmatch(cycle_id) is None:
        raise RevisitContractError("cycle_id must match RC-NNNN")
    return cycle_id


def cycle_json_path(workspace: str | Path, cycle_id: str) -> Path:
    cycle_id = _require_cycle_id(cycle_id)
    return resolve_workspace_path(
        workspace,
        f"{CYCLES_DIRNAME}/{cycle_id}.json",
        parent=CYCLES_DIRNAME,
        suffix=".json",
    )


def cycle_markdown_path(workspace: str | Path, cycle_id: str) -> Path:
    cycle_id = _require_cycle_id(cycle_id)
    return resolve_workspace_path(
        workspace,
        f"{CYCLES_DIRNAME}/{cycle_id}.md",
        parent=CYCLES_DIRNAME,
        suffix=".md",
    )


def _read_json_authority(path: Path, authority: str) -> Any:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise RevisitContractError(f"{authority} authority is missing: {path.name}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError(f"malformed JSON authority: {path.name}") from exc


def load_pointer(
    workspace: str | Path, allow_missing: bool = False
) -> dict[str, Any] | None:
    path = pointer_path(workspace)
    if allow_missing and not path.exists():
        return None
    return validate_pointer(_read_json_authority(path, "pointer"))


def load_cycle(workspace: str | Path, cycle_id: str) -> dict[str, Any]:
    cycle_id = _require_cycle_id(cycle_id)
    cycle = validate_cycle(_read_json_authority(cycle_json_path(workspace, cycle_id), "cycle"))
    if cycle["cycle_id"] != cycle_id:
        raise RevisitContractError(
            f"filename {cycle_id} does not match internal cycle_id {cycle['cycle_id']}"
        )
    return cycle


def list_cycle_ids(workspace: str | Path) -> tuple[str, ...]:
    directory = cycle_directory(workspace)
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise RevisitContractError(f"cycle authority directory is not a directory: {directory.name}")
    discovered = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name.endswith(".json"):
            cycle_id = path.name.removesuffix(".json")
            match = CYCLE_ID_RE.fullmatch(cycle_id)
            if match is None or not path.is_file():
                raise RevisitContractError(f"malformed cycle filename: {path.name}")
            cycle = load_cycle(workspace, cycle_id)
            if cycle["cycle_id"] != cycle_id:
                raise RevisitContractError(
                    f"filename {cycle_id} does not match internal cycle_id {cycle['cycle_id']}"
                )
            discovered.append((int(match.group("number")), cycle_id))
            continue
        if path.name.endswith(".md"):
            cycle_id = path.name.removesuffix(".md")
            if CYCLE_ID_RE.fullmatch(cycle_id) is not None and path.is_file():
                continue
        raise RevisitContractError(f"malformed cycle filename: {path.name}")
    cycle_ids = [cycle_id for _, cycle_id in sorted(discovered)]
    if len(cycle_ids) != len(set(cycle_ids)):
        raise RevisitContractError("duplicate cycle IDs in history")
    return tuple(cycle_ids)


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _require_expected_bytes(path: Path, expected_sha256: str | None) -> bytes | None:
    if not path.exists():
        if expected_sha256 is not None:
            raise RevisitContractError(
                f"authority disappeared before write: {path.name}"
            )
        return None
    original = path.read_bytes()
    if expected_sha256 is None or sha256_bytes(original) != expected_sha256:
        raise RevisitContractError(f"authority changed before write: {path.name}")
    return original


def persist_pointer(
    workspace: str | Path,
    pointer: dict[str, Any],
    expected_sha256: str | None,
) -> Path:
    validate_pointer(pointer)
    path = pointer_path(workspace)
    _require_expected_bytes(path, expected_sha256)
    payload = canonical_document_bytes(pointer)
    _atomic_replace(path, payload)
    return path


def persist_cycle(
    workspace: str | Path,
    cycle: dict[str, Any],
    expected_sha256: str | None,
) -> tuple[Path, Path]:
    validate_cycle(cycle)
    json_path = cycle_json_path(workspace, cycle["cycle_id"])
    markdown_path = cycle_markdown_path(workspace, cycle["cycle_id"])
    if json_path == markdown_path:
        raise RevisitContractError(
            "cycle JSON and Markdown authority targets must be distinct"
        )
    _require_expected_bytes(json_path, expected_sha256)
    prior_markdown = markdown_path.read_bytes() if markdown_path.exists() else None
    markdown_payload = render_cycle_markdown(cycle).encode("utf-8")
    json_payload = canonical_document_bytes(cycle)
    _atomic_replace(markdown_path, markdown_payload)
    try:
        _atomic_replace(json_path, json_payload)
    except Exception as original_error:
        try:
            if prior_markdown is None:
                if markdown_path.exists():
                    markdown_path.unlink()
            else:
                _atomic_replace(markdown_path, prior_markdown)
        except Exception as rollback_error:
            raise RevisitPersistenceRollbackError(
                original_error, rollback_error
            ) from rollback_error
        raise
    return json_path, markdown_path
