from __future__ import annotations

import hashlib
import os
import stat as stat_module
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, Union

from .model import RevisitContractError

EntryKind = Literal["file", "directory", "other"]


@dataclass(frozen=True)
class ObservedEntry:
    relative_path: str
    kind: EntryKind
    resolved_target: Path


@dataclass(frozen=True)
class FileGeneration:
    relative_path: str
    resolved_target: Path
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class AbsentGeneration:
    relative_path: str


@dataclass(frozen=True)
class DirectoryGeneration:
    relative_path: str
    resolved_target: Path
    recursive: bool
    entries: tuple[ObservedEntry, ...]


@dataclass(frozen=True)
class GenerationDrift:
    relative_path: str
    message: str


class AuthorityDriftError(RevisitContractError):
    """Raised when an observed generation changed before the closure check.

    Carries the exact GenerationDrift on the .drift attribute. Subclass
    RevisitContractError so callers in the revisit domain catch it uniformly.
    """

    def __init__(self, drift: GenerationDrift) -> None:
        self.drift = drift
        super().__init__(
            f"authority drift for {drift.relative_path}: {drift.message}"
        )


def normalize_relative_path(value: str) -> str:
    """Normalize a workspace-relative path to canonical POSIX form.

    Rejects empty input, control characters, absolute POSIX paths, Windows
    drive/root/UNC roots, and any ``..`` segment that escapes the workspace.
    Backslashes are treated as separators; ``.`` and empty segments collapse.
    """
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


def _resolve_member_target(workspace: Path, relative: str) -> Path:
    """Resolve a normalized relative path under workspace, enforcing containment.

    ``strict=False`` so symlinks-to-existing-targets still resolve; containment
    is enforced by checking the resolved path stays under the workspace.
    """
    resolved = (workspace / relative).resolve(strict=False)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise RevisitContractError(
            f"path escapes workspace: {relative}"
        ) from exc
    return resolved


def _classify_entry(path: Path) -> EntryKind:
    """Classify a lexical entry by its OWN type (symlinks are 'other').

    Uses ``os.lstat`` so a symbolic link is reported as ``"other"`` rather than
    the type of its target; this is what makes member symlink retarget drift
    observable even when the new target shares a kind with the old one.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return "other"
    mode = info.st_mode
    if stat_module.S_ISDIR(mode):
        return "directory"
    if stat_module.S_ISREG(mode):
        return "file"
    return "other"


Generation = Union[FileGeneration, AbsentGeneration, DirectoryGeneration]


@dataclass(frozen=True)
class GenerationClosure:
    workspace: Path
    generations: tuple[Generation, ...]

    def require_unchanged(self) -> None:
        """Recheck every generation against the current filesystem; raise
        AuthorityDriftError on any byte/target/absence/membership change."""
        _verify_generations(self, frozenset())


def _verify_file_generation(
    gen: FileGeneration, excluded: frozenset[str], workspace: Path
) -> None:
    if gen.relative_path in excluded:
        return
    expected = gen.resolved_target
    current = _resolve_member_target(workspace, gen.relative_path)
    if current != expected:
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                f"resolved target changed: {expected} -> {current}",
            )
        )
    if not current.is_file():
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path, "required file is no longer present"
            )
        )
    try:
        payload = current.read_bytes()
    except FileNotFoundError as exc:
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path, "required file disappeared before recheck"
            )
        ) from exc
    if payload != gen.payload:
        raise AuthorityDriftError(
            GenerationDrift(gen.relative_path, "file bytes changed")
        )


def _verify_absent_generation(
    gen: AbsentGeneration, excluded: frozenset[str], workspace: Path
) -> None:
    if gen.relative_path in excluded:
        return
    resolved = _resolve_member_target(workspace, gen.relative_path)
    if resolved.exists():
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                "previously-absent path now exists",
            )
        )


def _walk_directory(
    workspace: Path, relative: str, recursive: bool
) -> tuple[ObservedEntry, ...]:
    """Return direct (or recursive) members of a directory, POSIX-sorted."""
    root = _resolve_member_target(workspace, relative)
    members: list[ObservedEntry] = []

    def visit(dir_relative: str) -> None:
        dir_target = _resolve_member_target(workspace, dir_relative)
        try:
            children = sorted(dir_target.iterdir(), key=lambda p: p.name)
        except FileNotFoundError as exc:
            raise RevisitContractError(
                f"directory disappeared during listing: {dir_relative}"
            ) from exc
        for child in children:
            child_rel = f"{dir_relative}/{child.name}"
            child_target = _resolve_member_target(workspace, child_rel)
            kind = _classify_entry(workspace / child_rel)
            members.append(
                ObservedEntry(
                    relative_path=child_rel,
                    kind=kind,
                    resolved_target=child_target,
                )
            )
            if recursive and kind == "directory":
                visit(child_rel)

    visit(relative)
    members.sort(key=lambda e: e.relative_path)
    return tuple(members)


def _verify_directory_generation(
    gen: DirectoryGeneration, excluded: frozenset[str], workspace: Path
) -> None:
    target = gen.resolved_target
    current_target = _resolve_member_target(workspace, gen.relative_path)
    if current_target != target:
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path,
                f"directory target changed: {target} -> {current_target}",
            )
        )
    if not current_target.is_dir():
        raise AuthorityDriftError(
            GenerationDrift(
                gen.relative_path, "directory is no longer present"
            )
        )
    observed = _walk_directory(workspace, gen.relative_path, gen.recursive)
    expected_map = {
        e.relative_path: e
        for e in gen.entries
        if e.relative_path not in excluded
    }
    current_map = {
        e.relative_path: e for e in observed if e.relative_path not in excluded
    }
    expected_keys = set(expected_map)
    current_keys = set(current_map)
    if expected_keys != current_keys:
        missing = sorted(expected_keys - current_keys)
        added = sorted(current_keys - expected_keys)
        detail = []
        if missing:
            detail.append(f"members removed: {missing}")
        if added:
            detail.append(f"members added: {added}")
        raise AuthorityDriftError(
            GenerationDrift(gen.relative_path, "; ".join(detail))
        )
    for key in sorted(expected_keys):
        before = expected_map[key]
        after = current_map[key]
        if before.kind != after.kind:
            raise AuthorityDriftError(
                GenerationDrift(
                    gen.relative_path,
                    f"member kind changed at {key}: "
                    f"{before.kind} -> {after.kind}",
                )
            )
        if before.resolved_target != after.resolved_target:
            raise AuthorityDriftError(
                GenerationDrift(
                    gen.relative_path,
                    f"member target changed at {key}: "
                    f"{before.resolved_target} -> {after.resolved_target}",
                )
            )


def _verify_generations(
    closure: GenerationClosure, excluded: frozenset[str]
) -> None:
    for gen in closure.generations:
        if isinstance(gen, FileGeneration):
            _verify_file_generation(gen, excluded, closure.workspace)
        elif isinstance(gen, AbsentGeneration):
            _verify_absent_generation(gen, excluded, closure.workspace)
        elif isinstance(gen, DirectoryGeneration):
            _verify_directory_generation(gen, excluded, closure.workspace)
        else:  # pragma: no cover - defensive, frozen dataclasses are typed
            raise RevisitContractError(
                f"unsupported generation type: {type(gen).__name__}"
            )


def _require_unchanged_except(
    closure: GenerationClosure, excluded_relative_paths: tuple[str, ...]
) -> None:
    """MODULE-PRIVATE: like ``require_unchanged`` but exclude exact member paths.

    Excluded paths are dropped from BOTH the expected and current directory
    membership before comparison (only those exact member paths; the directory
    target and all other members are still verified). For FileGeneration /
    AbsentGeneration an excluded path is skipped entirely. Only ``str`` values
    are accepted; anything else is rejected as a programming error.
    """
    normalized_excluded: set[str] = set()
    for value in excluded_relative_paths:
        if not isinstance(value, str):
            raise RevisitContractError(
                "excluded relative paths must be strings"
            )
        normalized_excluded.add(normalize_relative_path(value))
    _verify_generations(closure, frozenset(normalized_excluded))


class ObservedReadSession:
    """Observes filesystem authority and freezes a drift-detecting closure.

    Each observation captures the FIRST bytes / absence / directory membership
    seen for a given lexical path (keyed by ``(relative_path, recursive)`` for
    directories) and caches it. A subsequent call returns the cached value
    regardless of later disk mutation. ``freeze`` returns an immutable
    ``GenerationClosure`` whose ``require_unchanged`` re-checks the filesystem
    against the cached observations.
    """

    def __init__(self, workspace: str | Path) -> None:
        self._workspace = Path(workspace).resolve()
        self._directory_cache: dict[tuple[str, bool], tuple[ObservedEntry, ...]] = {}
        # File/absent generations are keyed by normalized relative path; the
        # first observation for a path wins and is never overwritten.
        self._path_generations: dict[str, Generation] = {}
        # Directory generations are keyed by (relative_path, recursive) because
        # the two recursion modes are independent observations of one lexical
        # directory that observe different member sets.
        self._directory_generations: dict[tuple[str, bool], DirectoryGeneration] = {}
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RevisitContractError(
                "ObservedReadSession is closed after freeze()"
            )

    def _record_path(self, relative: str, generation: Generation) -> None:
        # First observation wins: never overwrite an existing generation.
        self._path_generations.setdefault(relative, generation)

    def read_required(self, relative_path: str) -> bytes:
        self._ensure_open()
        relative = normalize_relative_path(relative_path)
        observed = self._path_generations.get(relative)
        if isinstance(observed, FileGeneration):
            return observed.payload
        if isinstance(observed, AbsentGeneration):
            raise RevisitContractError(
                f"required authority is missing: {relative}"
            )
        resolved = _resolve_member_target(self._workspace, relative)
        try:
            payload = resolved.read_bytes()
        except FileNotFoundError:
            self._record_path(relative, AbsentGeneration(relative_path=relative))
            raise RevisitContractError(
                f"required authority is missing: {relative}"
            )
        self._record_path(
            relative,
            FileGeneration(
                relative_path=relative,
                resolved_target=resolved,
                payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        )
        return payload

    def read_optional(self, relative_path: str) -> bytes | None:
        self._ensure_open()
        relative = normalize_relative_path(relative_path)
        observed = self._path_generations.get(relative)
        if isinstance(observed, FileGeneration):
            return observed.payload
        if isinstance(observed, AbsentGeneration):
            return None
        resolved = _resolve_member_target(self._workspace, relative)
        try:
            payload = resolved.read_bytes()
        except FileNotFoundError:
            self._record_path(relative, AbsentGeneration(relative_path=relative))
            return None
        self._record_path(
            relative,
            FileGeneration(
                relative_path=relative,
                resolved_target=resolved,
                payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        )
        return payload

    def list_directory(
        self,
        relative_path: str,
        *,
        recursive: bool,
        optional: bool = False,
    ) -> tuple[ObservedEntry, ...]:
        self._ensure_open()
        relative = normalize_relative_path(relative_path)
        observed = self._path_generations.get(relative)
        if isinstance(observed, AbsentGeneration):
            if optional:
                return ()
            raise RevisitContractError(
                f"required directory is missing: {relative}"
            )
        cache_key = (relative, recursive)
        if cache_key in self._directory_cache:
            return self._directory_cache[cache_key]
        resolved = _resolve_member_target(self._workspace, relative)
        if not resolved.is_dir():
            # Record absence tombstone keyed by the lexical path so later
            # appearance still drifts. First observation wins.
            self._record_path(relative, AbsentGeneration(relative_path=relative))
            if optional:
                self._directory_cache[cache_key] = ()
                return ()
            raise RevisitContractError(
                f"required directory is missing: {relative}"
            )
        entries = _walk_directory(self._workspace, relative, recursive)
        self._directory_cache[cache_key] = entries
        self._directory_generations[cache_key] = DirectoryGeneration(
            relative_path=relative,
            resolved_target=resolved,
            recursive=recursive,
            entries=entries,
        )
        return entries

    def freeze(self) -> GenerationClosure:
        self._ensure_open()
        self._closed = True
        combined: list[Generation] = list(self._path_generations.values())
        combined.extend(self._directory_generations.values())
        generations = tuple(
            sorted(combined, key=lambda g: g.relative_path)
        )
        return GenerationClosure(
            workspace=self._workspace, generations=generations
        )
