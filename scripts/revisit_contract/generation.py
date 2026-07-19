from __future__ import annotations

import errno
import hashlib
import os
import stat as stat_module
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, Union

from .model import RevisitContractError

EntryKind = Literal["file", "directory", "other"]
_NodeState = Literal[
    "absent",
    "file",
    "directory",
    "symlink_file",
    "symlink_directory",
    "symlink_special",
    "broken_symlink",
    "outside",
    "special",
    "unreadable",
]


@dataclass(frozen=True)
class ObservedEntry:
    relative_path: str
    kind: EntryKind
    resolved_target: Path | None
    lexical_state: _NodeState | Literal["unknown"] = "unknown"


@dataclass(frozen=True)
class FileGeneration:
    relative_path: str
    resolved_target: Path
    payload: bytes
    sha256: str
    lexical_state: _NodeState = "file"


@dataclass(frozen=True)
class AbsentGeneration:
    relative_path: str
    resolved_target: Path


@dataclass(frozen=True)
class DirectoryGeneration:
    """One lexical directory's first-observed direct membership."""

    relative_path: str
    resolved_target: Path
    entries: tuple[ObservedEntry, ...]
    lexical_state: _NodeState = "directory"


@dataclass(frozen=True)
class _PresentInvalidGeneration:
    """A stable present node that was invalid for the requested operation."""

    relative_path: str
    lexical_kind: EntryKind
    lexical_state: _NodeState
    resolved_target: Path | None
    error_code: int | None = None
    operation: Literal["node", "read", "list"] = "node"


@dataclass(frozen=True)
class GenerationDrift:
    relative_path: str
    message: str


class AuthorityDriftError(RevisitContractError):
    """Raised when an observed lexical generation changes before recheck."""

    def __init__(self, drift: GenerationDrift) -> None:
        self.drift = drift
        super().__init__(
            f"authority drift for {drift.relative_path}: {drift.message}"
        )


class _ObservedReadSessionClosedError(RuntimeError):
    """A programming error caused by observing after session freeze."""


def normalize_relative_path(value: str) -> str:
    """Normalize a workspace-relative path to canonical POSIX form."""
    raw = str(value)
    if not raw or any(unicodedata.category(char) == "Cc" for char in raw):
        raise RevisitContractError(
            "workspace-relative path must be non-empty and control-free"
        )
    windows = PureWindowsPath(raw)
    if Path(raw).is_absolute() or windows.drive or windows.root:
        raise RevisitContractError(
            f"absolute workspace path is forbidden: {raw!r}"
        )
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise RevisitContractError(
            f"workspace path contains forbidden '..': {raw!r}"
        )
    normalized = "/".join(
        part for part in parts if part not in {"", "."}
    )
    if not normalized:
        raise RevisitContractError(
            "workspace-relative path resolves to empty"
        )
    return normalized


@dataclass(frozen=True)
class _NodeSignature:
    state: _NodeState
    lexical_kind: EntryKind
    resolved_target: Path | None
    error_code: int | None = None


@dataclass
class _ObservedNode:
    relative_path: str
    signature: _NodeSignature
    directly_observed: bool = False
    payload_observed: bool = False
    payload: bytes | None = None
    read_error_code: int | None = None
    direct_members_observed: bool = False
    direct_members: tuple[ObservedEntry, ...] = ()
    list_error_code: int | None = None


@dataclass(frozen=True)
class _ScannedEntry:
    entry: ObservedEntry
    signature: _NodeSignature


def _lexical_kind(mode: int) -> EntryKind:
    if stat_module.S_ISREG(mode):
        return "file"
    if stat_module.S_ISDIR(mode):
        return "directory"
    return "other"


def _is_within_workspace(workspace: Path, target: Path) -> bool:
    try:
        target.relative_to(workspace)
    except ValueError:
        return False
    return True


def _is_expected_input_os_error(exc: OSError) -> bool:
    """Return whether an OS error is a stable expected-input condition."""
    return isinstance(exc, PermissionError) or exc.errno in {
        errno.EACCES,
        errno.EPERM,
        errno.ENOTDIR,
        errno.ELOOP,
    }


def _resolve_lexical_path(path: Path) -> tuple[Path | None, int | None]:
    try:
        return path.resolve(strict=False), None
    except RuntimeError:
        return None, errno.ELOOP
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        return None, exc.errno


def _inspect_missing_path(
    workspace: Path,
    relative: str,
) -> _NodeSignature:
    """Prove that a FileNotFound path is true absence, not unsafe ancestry."""
    lexical_path = workspace / relative
    resolved, resolve_error = _resolve_lexical_path(lexical_path)
    if resolve_error is not None:
        return _NodeSignature(
            "unreadable",
            "other",
            resolved,
            resolve_error,
        )
    assert resolved is not None
    if not _is_within_workspace(workspace, resolved):
        return _NodeSignature("outside", "other", resolved)

    prefix = workspace
    for part in relative.split("/")[:-1]:
        prefix /= part
        try:
            prefix_stat = os.lstat(prefix)
        except FileNotFoundError:
            return _NodeSignature("absent", "other", resolved)
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            return _NodeSignature(
                "unreadable",
                "other",
                None,
                exc.errno,
            )
        if stat_module.S_ISDIR(prefix_stat.st_mode):
            continue
        if not stat_module.S_ISLNK(prefix_stat.st_mode):
            prefix_target, prefix_error = _resolve_lexical_path(prefix)
            return _NodeSignature(
                "unreadable",
                "other",
                prefix_target,
                prefix_error or errno.ENOTDIR,
            )
        prefix_target, prefix_error = _resolve_lexical_path(prefix)
        if prefix_error is not None:
            return _NodeSignature(
                "broken_symlink",
                "other",
                prefix_target,
                prefix_error,
            )
        assert prefix_target is not None
        if not _is_within_workspace(workspace, prefix_target):
            return _NodeSignature("outside", "other", resolved)
        try:
            target_stat = os.stat(prefix)
        except (FileNotFoundError, NotADirectoryError):
            return _NodeSignature(
                "broken_symlink",
                "other",
                prefix_target,
            )
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            return _NodeSignature(
                "unreadable",
                "other",
                prefix_target,
                exc.errno,
            )
        if not stat_module.S_ISDIR(target_stat.st_mode):
            return _NodeSignature(
                "unreadable",
                "other",
                prefix_target,
                errno.ENOTDIR,
            )
    return _NodeSignature("absent", "other", resolved)


def _inspect_node(workspace: Path, relative: str) -> _NodeSignature:
    """Classify a lexical node with lstat before any file or directory read."""
    lexical_path = workspace / relative
    try:
        lexical_stat = os.lstat(lexical_path)
    except FileNotFoundError:
        return _inspect_missing_path(workspace, relative)
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        return _NodeSignature(
            "unreadable",
            "other",
            None,
            exc.errno,
        )

    kind = _lexical_kind(lexical_stat.st_mode)
    resolved, resolve_error = _resolve_lexical_path(lexical_path)
    if resolve_error is not None:
        state: _NodeState = (
            "broken_symlink"
            if stat_module.S_ISLNK(lexical_stat.st_mode)
            else "unreadable"
        )
        return _NodeSignature(state, kind, resolved, resolve_error)
    assert resolved is not None
    if not _is_within_workspace(workspace, resolved):
        return _NodeSignature("outside", kind, resolved)

    if stat_module.S_ISREG(lexical_stat.st_mode):
        return _NodeSignature("file", "file", resolved)
    if stat_module.S_ISDIR(lexical_stat.st_mode):
        return _NodeSignature("directory", "directory", resolved)
    if not stat_module.S_ISLNK(lexical_stat.st_mode):
        return _NodeSignature("special", "other", resolved)

    try:
        target_stat = os.stat(lexical_path)
    except (FileNotFoundError, NotADirectoryError):
        return _NodeSignature("broken_symlink", "other", resolved)
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        return _NodeSignature(
            "unreadable",
            "other",
            resolved,
            exc.errno,
        )
    if stat_module.S_ISREG(target_stat.st_mode):
        return _NodeSignature("symlink_file", "other", resolved)
    if stat_module.S_ISDIR(target_stat.st_mode):
        return _NodeSignature("symlink_directory", "other", resolved)
    return _NodeSignature("symlink_special", "other", resolved)


def _signature_description(signature: _NodeSignature) -> str:
    detail = signature.state.replace("_", " ")
    if signature.error_code is not None:
        detail += f" (errno {signature.error_code})"
    return detail


def _raise_signature_drift(
    relative: str,
    expected: _NodeSignature,
    current: _NodeSignature,
) -> None:
    raise AuthorityDriftError(
        GenerationDrift(
            relative,
            "lexical state changed: "
            f"{_signature_description(expected)} -> "
            f"{_signature_description(current)}",
        )
    )


def _require_signature(
    workspace: Path,
    relative: str,
    expected: _NodeSignature,
) -> None:
    current = _inspect_node(workspace, relative)
    if current != expected:
        _raise_signature_drift(relative, expected, current)


def _entry_from_signature(
    relative: str,
    signature: _NodeSignature,
) -> ObservedEntry:
    return ObservedEntry(
        relative_path=relative,
        kind=signature.lexical_kind,
        resolved_target=signature.resolved_target,
        lexical_state=signature.state,
    )


def _scan_direct_members(
    workspace: Path,
    relative: str,
    expected: _NodeSignature,
) -> tuple[_ScannedEntry, ...]:
    _require_signature(workspace, relative, expected)
    lexical_path = workspace / relative
    children = sorted(lexical_path.iterdir(), key=lambda path: path.name)
    _require_signature(workspace, relative, expected)
    entries: list[_ScannedEntry] = []
    for child in children:
        child_relative = f"{relative}/{child.name}"
        signature = _inspect_node(workspace, child_relative)
        entries.append(
            _ScannedEntry(
                entry=_entry_from_signature(child_relative, signature),
                signature=signature,
            )
        )
    return tuple(entries)


Generation = Union[
    FileGeneration,
    AbsentGeneration,
    DirectoryGeneration,
    _PresentInvalidGeneration,
]


@dataclass(frozen=True)
class GenerationClosure:
    workspace: Path
    generations: tuple[Generation, ...]

    def require_unchanged(self) -> None:
        """Recheck every observed lexical generation."""
        _verify_generations(self, frozenset())


def _file_expected_signature(gen: FileGeneration) -> _NodeSignature:
    kind: EntryKind = "file" if gen.lexical_state == "file" else "other"
    return _NodeSignature(
        gen.lexical_state,
        kind,
        gen.resolved_target,
    )


def _verify_file_generation(
    gen: FileGeneration,
    excluded: frozenset[str],
    workspace: Path,
) -> None:
    if gen.relative_path in excluded:
        return
    expected = _file_expected_signature(gen)
    _require_signature(workspace, gen.relative_path, expected)
    try:
        payload = gen.resolved_target.read_bytes()
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                f"observed file is no longer readable: {exc}",
            )
        ) from exc
    _require_signature(workspace, gen.relative_path, expected)
    if payload != gen.payload:
        raise AuthorityDriftError(
            GenerationDrift(gen.relative_path, "file bytes changed")
        )


def _verify_absent_generation(
    gen: AbsentGeneration,
    excluded: frozenset[str],
    workspace: Path,
) -> None:
    if gen.relative_path in excluded:
        return
    current = _inspect_node(workspace, gen.relative_path)
    expected = _NodeSignature("absent", "other", gen.resolved_target)
    if current != expected:
        _raise_signature_drift(gen.relative_path, expected, current)


def _directory_expected_signature(
    gen: DirectoryGeneration,
) -> _NodeSignature:
    return _NodeSignature(
        gen.lexical_state,
        "directory",
        gen.resolved_target,
    )


def _verify_directory_generation(
    gen: DirectoryGeneration,
    excluded: frozenset[str],
    workspace: Path,
) -> None:
    if gen.relative_path in excluded:
        return
    expected_signature = _directory_expected_signature(gen)
    _require_signature(workspace, gen.relative_path, expected_signature)
    try:
        observed = tuple(
            scanned.entry
            for scanned in _scan_direct_members(
                workspace,
                gen.relative_path,
                expected_signature,
            )
        )
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                f"observed directory is no longer readable: {exc}",
            )
        ) from exc

    expected_map = {
        entry.relative_path: entry
        for entry in gen.entries
        if entry.relative_path not in excluded
    }
    current_map = {
        entry.relative_path: entry
        for entry in observed
        if entry.relative_path not in excluded
    }
    missing = sorted(set(expected_map) - set(current_map))
    if missing:
        raise AuthorityDriftError(
            GenerationDrift(missing[0], "directory member was removed")
        )
    added = sorted(set(current_map) - set(expected_map))
    if added:
        raise AuthorityDriftError(
            GenerationDrift(added[0], "directory member was added")
        )
    for relative in sorted(expected_map):
        before = expected_map[relative]
        after = current_map[relative]
        if before != after:
            raise AuthorityDriftError(
                GenerationDrift(
                    relative,
                    "directory member lexical state or target changed",
                )
            )


def _present_invalid_signature(
    gen: _PresentInvalidGeneration,
) -> _NodeSignature:
    return _NodeSignature(
        gen.lexical_state,
        gen.lexical_kind,
        gen.resolved_target,
        gen.error_code if gen.operation == "node" else None,
    )


def _verify_present_invalid_generation(
    gen: _PresentInvalidGeneration,
    excluded: frozenset[str],
    workspace: Path,
) -> None:
    if gen.relative_path in excluded:
        return
    expected = _present_invalid_signature(gen)
    _require_signature(workspace, gen.relative_path, expected)
    if gen.operation == "read":
        assert gen.resolved_target is not None
        try:
            gen.resolved_target.read_bytes()
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            if exc.errno == gen.error_code:
                return
            raise AuthorityDriftError(
                GenerationDrift(
                    gen.relative_path,
                    "file readability failure changed",
                )
            ) from exc
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                "previously unreadable file became readable",
            )
        )
    if gen.operation == "list":
        try:
            tuple((workspace / gen.relative_path).iterdir())
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            if exc.errno == gen.error_code:
                return
            raise AuthorityDriftError(
                GenerationDrift(
                    gen.relative_path,
                    "directory readability failure changed",
                )
            ) from exc
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                "previously unreadable directory became readable",
            )
        )


def _verify_generations(
    closure: GenerationClosure,
    excluded: frozenset[str],
) -> None:
    for generation in closure.generations:
        if isinstance(generation, FileGeneration):
            _verify_file_generation(generation, excluded, closure.workspace)
        elif isinstance(generation, AbsentGeneration):
            _verify_absent_generation(generation, excluded, closure.workspace)
        elif isinstance(generation, DirectoryGeneration):
            _verify_directory_generation(
                generation,
                excluded,
                closure.workspace,
            )
        elif isinstance(generation, _PresentInvalidGeneration):
            _verify_present_invalid_generation(
                generation,
                excluded,
                closure.workspace,
            )
        else:  # pragma: no cover - defensive against impossible construction
            raise RevisitContractError(
                f"unsupported generation type: {type(generation).__name__}"
            )


def _require_unchanged_except(
    closure: GenerationClosure,
    excluded_relative_paths: tuple[str, ...],
) -> None:
    """Recheck a closure while excluding exact declared mutation paths."""
    normalized_excluded: set[str] = set()
    for value in excluded_relative_paths:
        if not isinstance(value, str):
            raise RevisitContractError(
                "excluded relative paths must be strings"
            )
        normalized_excluded.add(normalize_relative_path(value))
    _verify_generations(closure, frozenset(normalized_excluded))


class ObservedReadSession:
    """One first-observed lexical-node authority for a readiness evaluation."""

    def __init__(self, workspace: str | Path) -> None:
        self._workspace = Path(workspace).resolve()
        self._nodes: dict[str, _ObservedNode] = {}
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise _ObservedReadSessionClosedError(
                "ObservedReadSession is closed after freeze()"
            )

    def _node(
        self,
        relative: str,
        *,
        directly_observed: bool,
    ) -> _ObservedNode:
        node = self._nodes.get(relative)
        if node is None:
            node = _ObservedNode(
                relative_path=relative,
                signature=_inspect_node(self._workspace, relative),
            )
            self._nodes[relative] = node
        if directly_observed:
            node.directly_observed = True
        return node

    def _operation_error(
        self,
        node: _ObservedNode,
        expected: str,
    ) -> RevisitContractError:
        return RevisitContractError(
            f"{node.relative_path} is present but is not a readable "
            f"{expected}: {_signature_description(node.signature)}"
        )

    def _capture_payload(self, node: _ObservedNode) -> bytes:
        if node.payload_observed:
            if node.read_error_code is not None:
                raise self._operation_error(node, "file")
            assert node.payload is not None
            return node.payload

        _require_signature(
            self._workspace,
            node.relative_path,
            node.signature,
        )
        assert node.signature.resolved_target is not None
        try:
            payload = node.signature.resolved_target.read_bytes()
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            current = _inspect_node(self._workspace, node.relative_path)
            if current != node.signature:
                _raise_signature_drift(
                    node.relative_path,
                    node.signature,
                    current,
                )
            node.payload_observed = True
            node.read_error_code = exc.errno
            raise self._operation_error(node, "file") from exc
        _require_signature(
            self._workspace,
            node.relative_path,
            node.signature,
        )
        node.payload_observed = True
        node.payload = payload
        return payload

    def _capture_direct_members(
        self,
        node: _ObservedNode,
    ) -> tuple[ObservedEntry, ...]:
        if node.direct_members_observed:
            if node.list_error_code is not None:
                raise self._operation_error(node, "directory")
            return node.direct_members

        try:
            scanned_entries = _scan_direct_members(
                self._workspace,
                node.relative_path,
                node.signature,
            )
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            current = _inspect_node(self._workspace, node.relative_path)
            if current != node.signature:
                _raise_signature_drift(
                    node.relative_path,
                    node.signature,
                    current,
                )
            node.direct_members_observed = True
            node.list_error_code = exc.errno
            raise self._operation_error(node, "directory") from exc

        canonical_entries: list[ObservedEntry] = []
        for scanned in scanned_entries:
            entry = scanned.entry
            child = self._nodes.get(entry.relative_path)
            if child is None:
                child = _ObservedNode(
                    relative_path=entry.relative_path,
                    signature=scanned.signature,
                )
                self._nodes[entry.relative_path] = child
            elif child.signature != scanned.signature:
                _raise_signature_drift(
                    child.relative_path,
                    child.signature,
                    scanned.signature,
                )
            canonical_entries.append(
                _entry_from_signature(
                    child.relative_path,
                    child.signature,
                )
            )
        node.direct_members_observed = True
        node.direct_members = tuple(canonical_entries)
        return node.direct_members

    def _compose_recursive(
        self,
        node: _ObservedNode,
    ) -> tuple[ObservedEntry, ...]:
        direct = self._capture_direct_members(node)
        composed: list[ObservedEntry] = list(direct)
        for entry in direct:
            if entry.kind != "directory":
                continue
            child = self._node(
                entry.relative_path,
                directly_observed=False,
            )
            composed.extend(self._compose_recursive(child))
        composed.sort(key=lambda entry: entry.relative_path)
        return tuple(composed)

    def _read(self, relative_path: str, *, optional: bool) -> bytes | None:
        self._ensure_open()
        relative = normalize_relative_path(relative_path)
        node = self._node(relative, directly_observed=True)
        if node.signature.state == "absent":
            if optional:
                return None
            raise RevisitContractError(
                f"required authority is missing: {relative}"
            )
        if node.signature.state not in {"file", "symlink_file"}:
            raise self._operation_error(node, "file")
        return self._capture_payload(node)

    def read_required(self, relative_path: str) -> bytes:
        payload = self._read(relative_path, optional=False)
        assert payload is not None
        return payload

    def read_optional(self, relative_path: str) -> bytes | None:
        return self._read(relative_path, optional=True)

    def list_directory(
        self,
        relative_path: str,
        *,
        recursive: bool,
        optional: bool = False,
    ) -> tuple[ObservedEntry, ...]:
        self._ensure_open()
        relative = normalize_relative_path(relative_path)
        node = self._node(relative, directly_observed=True)
        if node.signature.state == "absent":
            if optional:
                return ()
            raise RevisitContractError(
                f"required directory is missing: {relative}"
            )
        if node.signature.state != "directory":
            raise self._operation_error(node, "directory")
        if recursive:
            return self._compose_recursive(node)
        return self._capture_direct_members(node)

    def _generation_for_node(
        self,
        node: _ObservedNode,
    ) -> Generation | None:
        if (
            not node.directly_observed
            and not node.payload_observed
            and not node.direct_members_observed
        ):
            return None
        if node.signature.state == "absent":
            assert node.signature.resolved_target is not None
            return AbsentGeneration(
                node.relative_path,
                node.signature.resolved_target,
            )
        if node.payload_observed and node.payload is not None:
            assert node.signature.resolved_target is not None
            return FileGeneration(
                relative_path=node.relative_path,
                resolved_target=node.signature.resolved_target,
                payload=node.payload,
                sha256=hashlib.sha256(node.payload).hexdigest(),
                lexical_state=node.signature.state,
            )
        if node.direct_members_observed and node.list_error_code is None:
            assert node.signature.resolved_target is not None
            return DirectoryGeneration(
                relative_path=node.relative_path,
                resolved_target=node.signature.resolved_target,
                entries=node.direct_members,
                lexical_state=node.signature.state,
            )
        operation: Literal["node", "read", "list"] = "node"
        error_code = node.signature.error_code
        if node.read_error_code is not None:
            operation = "read"
            error_code = node.read_error_code
        elif node.list_error_code is not None:
            operation = "list"
            error_code = node.list_error_code
        return _PresentInvalidGeneration(
            relative_path=node.relative_path,
            lexical_kind=node.signature.lexical_kind,
            lexical_state=node.signature.state,
            resolved_target=node.signature.resolved_target,
            error_code=error_code,
            operation=operation,
        )

    def freeze(self) -> GenerationClosure:
        self._ensure_open()
        self._closed = True
        generations = tuple(
            generation
            for relative in sorted(self._nodes)
            if (
                generation := self._generation_for_node(
                    self._nodes[relative]
                )
            )
            is not None
        )
        return GenerationClosure(
            workspace=self._workspace,
            generations=generations,
        )
