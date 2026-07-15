from __future__ import annotations

import hashlib
import errno
import json
import os
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from .model import (
    CYCLES_DIRNAME,
    CYCLE_ID_RE,
    POINTER_FILENAME,
    SHA256_RE,
    RevisitContractError,
    validate_cycle,
    validate_intake_request,
    validate_pointer,
)
from .render import render_cycle_markdown


_LOCK_DIRECTORY_NAME = "sofa-revisit-workspace-locks-v1"
_TRANSACTION_LOCAL = threading.local()


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


@dataclass(frozen=True)
class PreparedAuthoritySnapshot:
    workspace: Path
    lexical_path: Path
    resolved_target: Path
    expected_sha256: str


@dataclass(frozen=True)
class _AuthorityGeneration:
    snapshot: PreparedAuthoritySnapshot
    payload: bytes


_AuthoritySnapshots = (
    dict[Path, str] | tuple[PreparedAuthoritySnapshot, ...] | None
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


def _transaction_entries() -> dict[str, dict[str, Any]]:
    entries = getattr(_TRANSACTION_LOCAL, "entries", None)
    if entries is None:
        entries = {}
        _TRANSACTION_LOCAL.entries = entries
    return entries


def _workspace_transaction_key(workspace: Path) -> str:
    normalized = os.path.normcase(os.path.realpath(os.fspath(workspace)))
    return sha256_bytes(normalized.encode("utf-8"))


def _workspace_lock_path(workspace: Path) -> Path:
    directory = Path(tempfile.gettempdir()) / _LOCK_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / f"{_workspace_transaction_key(workspace)}.lock"


def _acquire_workspace_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        retry_errnos = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if (
                    exc.errno not in retry_errnos
                    and getattr(exc, "winerror", None) not in {33, 36}
                ):
                    raise
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_workspace_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def workspace_transaction(workspace: str | Path) -> Iterator[Path]:
    resolved_workspace = Path(workspace).resolve()
    key = _workspace_transaction_key(resolved_workspace)
    entries = _transaction_entries()
    existing = entries.get(key)
    current_pid = os.getpid()
    if existing is not None and existing["owner_pid"] != current_pid:
        del entries[key]
        existing["handle"].close()
        existing = None
    if existing is not None:
        existing["depth"] += 1
        try:
            yield existing["workspace"]
        finally:
            existing["depth"] -= 1
        return

    handle = _workspace_lock_path(resolved_workspace).open("a+b", buffering=0)
    try:
        _acquire_workspace_lock(handle)
    except Exception:
        handle.close()
        raise
    entries[key] = {
        "depth": 1,
        "handle": handle,
        "owner_pid": current_pid,
        "workspace": resolved_workspace,
    }
    try:
        yield resolved_workspace
    finally:
        del entries[key]
        try:
            _release_workspace_lock(handle)
        finally:
            handle.close()


def load_intake_request(path: str | Path) -> dict[str, Any]:
    request_path = Path(path)
    try:
        payload = request_path.read_bytes()
    except FileNotFoundError as exc:
        raise RevisitContractError(
            f"intake request is missing: {request_path}"
        ) from exc
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError(
            "intake request must be valid UTF-8 JSON"
        ) from exc
    return validate_intake_request(raw)


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


def verify_workspace_artifact(
    workspace: str | Path,
    value: str | Path,
    expected_sha256: str,
) -> tuple[str, bytes]:
    relative = normalize_workspace_relative_path(value)
    resolved = resolve_workspace_path(workspace, relative)
    if not resolved.is_file():
        raise RevisitContractError(f"artifact is not a file: {relative}")
    payload = resolved.read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise RevisitContractError(f"artifact hash mismatch: {relative}")
    return relative, payload


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


def _resolve_authority_identity(
    workspace: Path,
    raw_path: Path,
    *,
    lexical_workspace: Path | None = None,
) -> tuple[Path, Path]:
    input_root = Path(
        os.path.abspath(os.fspath(lexical_workspace or workspace))
    )
    raw = Path(raw_path)
    raw_absolute = Path(os.path.abspath(os.fspath(raw)))
    relative = None
    for candidate_root in (input_root, workspace):
        try:
            relative = raw_absolute.relative_to(candidate_root)
            break
        except ValueError:
            continue
    if relative is None:
        raise RevisitContractError(
            f"snapshot authority escapes workspace: {raw_path}"
        )
    lexical_path = workspace / relative
    resolved_target = lexical_path.resolve(strict=False)
    try:
        resolved_target.relative_to(workspace)
    except ValueError as exc:
        raise RevisitContractError(
            f"snapshot authority escapes workspace: {raw_path}"
        ) from exc
    return lexical_path, resolved_target


def _prepare_authority_snapshot(
    workspace: Path,
    raw_path: Path,
    expected_sha256: str,
    *,
    lexical_workspace: Path | None = None,
) -> PreparedAuthoritySnapshot:
    lexical_path, resolved_target = _resolve_authority_identity(
        workspace,
        raw_path,
        lexical_workspace=lexical_workspace,
    )
    if not isinstance(expected_sha256, str) or SHA256_RE.fullmatch(
        expected_sha256
    ) is None:
        raise RevisitContractError(
            "snapshot digest must be a lowercase SHA-256: "
            f"{lexical_path.name}"
        )
    return PreparedAuthoritySnapshot(
        workspace=workspace,
        lexical_path=lexical_path,
        resolved_target=resolved_target,
        expected_sha256=expected_sha256,
    )


def prepare_authority_snapshot(
    workspace: str | Path,
    lexical_path: Path,
    expected_sha256: str,
) -> PreparedAuthoritySnapshot:
    resolved_workspace = Path(workspace).resolve()
    return _prepare_authority_snapshot(
        resolved_workspace,
        lexical_path,
        expected_sha256,
        lexical_workspace=Path(workspace),
    )


def _read_authority_generation(
    workspace: str | Path,
    lexical_path: Path,
) -> _AuthorityGeneration:
    resolved_workspace = Path(workspace).resolve()
    canonical_path, resolved_target = _resolve_authority_identity(
        resolved_workspace,
        lexical_path,
        lexical_workspace=Path(workspace),
    )
    try:
        payload = resolved_target.read_bytes()
    except FileNotFoundError as exc:
        raise RevisitContractError(
            f"authority disappeared during generation capture: "
            f"{canonical_path.name}"
        ) from exc
    snapshot = PreparedAuthoritySnapshot(
        workspace=resolved_workspace,
        lexical_path=canonical_path,
        resolved_target=resolved_target,
        expected_sha256=sha256_bytes(payload),
    )
    return _AuthorityGeneration(snapshot=snapshot, payload=payload)


def _validate_prepared_authority_snapshot(
    workspace: Path,
    snapshot: PreparedAuthoritySnapshot,
) -> PreparedAuthoritySnapshot:
    if snapshot.workspace != workspace:
        raise RevisitContractError(
            "prepared snapshot belongs to a different workspace: "
            f"{snapshot.lexical_path.name}"
        )
    try:
        snapshot.lexical_path.relative_to(workspace)
        snapshot.resolved_target.relative_to(workspace)
    except ValueError as exc:
        raise RevisitContractError(
            "prepared snapshot authority escapes workspace: "
            f"{snapshot.lexical_path.name}"
        ) from exc
    if not isinstance(snapshot.expected_sha256, str) or SHA256_RE.fullmatch(
        snapshot.expected_sha256
    ) is None:
        raise RevisitContractError(
            "snapshot digest must be a lowercase SHA-256: "
            f"{snapshot.lexical_path.name}"
        )
    return snapshot


def _normalize_authority_snapshots(
    workspace: Path,
    snapshots: _AuthoritySnapshots,
    *,
    lexical_workspace: Path | None = None,
) -> dict[Path, PreparedAuthoritySnapshot]:
    normalized: dict[Path, PreparedAuthoritySnapshot] = {}
    if isinstance(snapshots, dict):
        prepared = tuple(
            _prepare_authority_snapshot(
                workspace,
                raw_path,
                expected_sha256,
                lexical_workspace=lexical_workspace,
            )
            for raw_path, expected_sha256 in snapshots.items()
        )
    elif snapshots is None:
        prepared = ()
    elif isinstance(snapshots, tuple):
        prepared = snapshots
    else:
        raise RevisitContractError(
            "authority_snapshots must be a path-digest dict or prepared tuple"
        )
    for value in prepared:
        if not isinstance(value, PreparedAuthoritySnapshot):
            raise RevisitContractError(
                "prepared authority snapshot has an unsupported value"
            )
        snapshot = _validate_prepared_authority_snapshot(workspace, value)
        existing = normalized.get(snapshot.lexical_path)
        if existing is not None and existing != snapshot:
            raise RevisitContractError(
                f"conflicting snapshot authority: {snapshot.lexical_path.name}"
            )
        normalized[snapshot.lexical_path] = snapshot
    return normalized


def _require_snapshot_generations(
    snapshots: dict[Path, PreparedAuthoritySnapshot], boundary: str
) -> None:
    for snapshot in snapshots.values():
        path = snapshot.lexical_path
        try:
            resolved_target = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RevisitContractError(
                f"authority disappeared {boundary}: {path.name}"
            ) from exc
        try:
            resolved_target.relative_to(snapshot.workspace)
        except ValueError as exc:
            raise RevisitContractError(
                f"snapshot authority escapes workspace {boundary}: {path.name}"
            ) from exc
        if resolved_target != snapshot.resolved_target:
            raise RevisitContractError(
                f"authority target changed {boundary}: {path.name}"
            )
        try:
            payload = resolved_target.read_bytes()
        except FileNotFoundError as exc:
            raise RevisitContractError(
                f"authority disappeared {boundary}: {path.name}"
            ) from exc
        if sha256_bytes(payload) != snapshot.expected_sha256:
            raise RevisitContractError(
                f"authority changed {boundary}: {path.name}"
            )


def _require_authority_generation(
    generation: _AuthorityGeneration,
    boundary: str,
) -> None:
    if not isinstance(generation, _AuthorityGeneration):
        raise RevisitContractError("authority generation has an unsupported value")
    _require_snapshot_generations(
        {generation.snapshot.lexical_path: generation.snapshot},
        boundary,
    )


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_committed_markdown(
    path: Path,
    written_payload: bytes,
    prior_payload: bytes | None,
) -> None:
    if _read_optional_bytes(path) != written_payload:
        raise RevisitContractError(
            "cycle Markdown changed after transaction write; rollback refused"
        )
    if prior_payload is None:
        path.unlink()
    else:
        _atomic_replace(path, prior_payload)


def _restore_committed_cycle_pair(
    *,
    json_path: Path,
    markdown_path: Path,
    written_json: bytes,
    written_markdown: bytes,
    prior_json: bytes | None,
    prior_markdown: bytes | None,
) -> None:
    if (
        _read_optional_bytes(json_path) != written_json
        or _read_optional_bytes(markdown_path) != written_markdown
    ):
        raise RevisitContractError(
            "cycle pair changed after transaction write; rollback refused"
        )
    if prior_markdown is None:
        markdown_path.unlink()
    else:
        _atomic_replace(markdown_path, prior_markdown)
    if prior_json is None:
        json_path.unlink()
    else:
        _atomic_replace(json_path, prior_json)


def _restore_committed_pointer(
    path: Path,
    written_payload: bytes,
    prior_payload: bytes | None,
) -> None:
    if _read_optional_bytes(path) != written_payload:
        raise RevisitContractError(
            "pointer changed after transaction write; rollback refused"
        )
    if prior_payload is None:
        path.unlink()
    else:
        _atomic_replace(path, prior_payload)


def persist_pointer(
    workspace: str | Path,
    pointer: dict[str, Any],
    expected_sha256: str | None,
    *,
    authority_snapshots: _AuthoritySnapshots = None,
) -> Path:
    lexical_workspace = Path(workspace)
    with workspace_transaction(workspace) as locked_workspace:
        validate_pointer(pointer)
        path = pointer_path(locked_workspace)
        snapshots = _normalize_authority_snapshots(
            locked_workspace,
            authority_snapshots,
            lexical_workspace=lexical_workspace,
        )
        prior_payload = _require_expected_bytes(path, expected_sha256)
        payload = canonical_document_bytes(pointer)
        _require_snapshot_generations(snapshots, "before pointer persistence")
        _atomic_replace(path, payload)
        try:
            _require_snapshot_generations(snapshots, "after pointer persistence")
        except Exception as original_error:
            try:
                _restore_committed_pointer(path, payload, prior_payload)
            except Exception as rollback_error:
                raise RevisitPersistenceRollbackError(
                    original_error, rollback_error
                ) from rollback_error
            raise
        return path


def persist_cycle(
    workspace: str | Path,
    cycle: dict[str, Any],
    expected_sha256: str | None,
    *,
    authority_snapshots: _AuthoritySnapshots = None,
) -> tuple[Path, Path]:
    lexical_workspace = Path(workspace)
    with workspace_transaction(workspace) as locked_workspace:
        validate_cycle(cycle)
        json_path = cycle_json_path(locked_workspace, cycle["cycle_id"])
        markdown_path = cycle_markdown_path(locked_workspace, cycle["cycle_id"])
        if json_path == markdown_path:
            raise RevisitContractError(
                "cycle JSON and Markdown authority targets must be distinct"
            )
        snapshots = _normalize_authority_snapshots(
            locked_workspace,
            authority_snapshots,
            lexical_workspace=lexical_workspace,
        )
        prior_json = _require_expected_bytes(json_path, expected_sha256)
        prior_markdown = markdown_path.read_bytes() if markdown_path.exists() else None
        markdown_payload = render_cycle_markdown(cycle).encode("utf-8")
        json_payload = canonical_document_bytes(cycle)
        _require_snapshot_generations(snapshots, "before cycle persistence")
        _atomic_replace(markdown_path, markdown_payload)
        try:
            _atomic_replace(json_path, json_payload)
        except Exception as original_error:
            try:
                _restore_committed_markdown(
                    markdown_path,
                    markdown_payload,
                    prior_markdown,
                )
            except Exception as rollback_error:
                raise RevisitPersistenceRollbackError(
                    original_error, rollback_error
                ) from rollback_error
            raise
        try:
            _require_snapshot_generations(snapshots, "after cycle persistence")
        except Exception as original_error:
            try:
                _restore_committed_cycle_pair(
                    json_path=json_path,
                    markdown_path=markdown_path,
                    written_json=json_payload,
                    written_markdown=markdown_payload,
                    prior_json=prior_json,
                    prior_markdown=prior_markdown,
                )
            except Exception as rollback_error:
                raise RevisitPersistenceRollbackError(
                    original_error, rollback_error
                ) from rollback_error
            raise
        return json_path, markdown_path
