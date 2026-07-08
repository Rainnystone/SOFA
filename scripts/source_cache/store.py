from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from .model import (
        DATE_FORMAT,
        EXCERPT_MAX_CHARS,
        GRADES,
        SOURCE_INDEX_FILENAME,
        SOURCES_DIRNAME,
        SourceCacheError,
        SourceCacheEvaluation,
        SourceIssue,
        _has_control_character,
        excerpt_sha256,
        format_source_id,
        normalize_excerpt_text,
        parse_source_number,
        source_ids_in_text,
        validate_record,
    )
except ImportError:
    from model import (
        DATE_FORMAT,
        EXCERPT_MAX_CHARS,
        GRADES,
        SOURCE_INDEX_FILENAME,
        SOURCES_DIRNAME,
        SourceCacheError,
        SourceCacheEvaluation,
        SourceIssue,
        _has_control_character,
        excerpt_sha256,
        format_source_id,
        normalize_excerpt_text,
        parse_source_number,
        source_ids_in_text,
        validate_record,
    )


def index_path(workspace: str | Path) -> Path:
    return Path(workspace) / SOURCE_INDEX_FILENAME


def load_index(workspace: str | Path) -> list[tuple[int, dict]]:
    path = index_path(workspace)
    if not path.exists():
        return []
    entries: list[tuple[int, dict]] = []
    try:
        index_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SourceCacheError(f"cannot read {SOURCE_INDEX_FILENAME} as UTF-8 text: {exc}") from exc
    for line_number, line in enumerate(index_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SourceCacheError(
                f"{SOURCE_INDEX_FILENAME}:{line_number} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise SourceCacheError(f"{SOURCE_INDEX_FILENAME}:{line_number} must be a JSON object")
        entries.append((line_number, value))
    return entries


def evaluate_index(workspace: str | Path) -> SourceCacheEvaluation:
    workspace_path = Path(workspace)
    try:
        entries = load_index(workspace_path)
    except SourceCacheError as exc:
        issue = SourceIssue("SOURCE_INDEX_MALFORMED", SOURCE_INDEX_FILENAME, str(exc))
        return SourceCacheEvaluation((), (issue,), ())

    issues: list[SourceIssue] = []
    warnings: list[SourceIssue] = []
    records: list[dict] = []
    seen_ids: dict[str, int] = {}
    seen_hashes: dict[str, str] = {}
    for line_number, record in entries:
        location = f"{SOURCE_INDEX_FILENAME}:{line_number}"
        record_issues = validate_record(record, line_number)
        if record_issues:
            issues.extend(record_issues)
            continue
        records.append(record)
        source_id = record["source_id"]
        if source_id in seen_ids:
            issues.append(
                SourceIssue(
                    "SOURCE_INDEX_MALFORMED",
                    location,
                    f"duplicate source_id {source_id} (first seen on line {seen_ids[source_id]})",
                )
            )
        else:
            seen_ids[source_id] = line_number
        digest = record["sha256"]
        if digest in seen_hashes:
            issues.append(
                SourceIssue(
                    "SOURCE_HASH_DUPLICATE",
                    location,
                    f"sha256 duplicates {seen_hashes[digest]} (the CLI dedupes; a duplicate means a hand edit)",
                )
            )
        else:
            seen_hashes[digest] = source_id
        excerpt_path = workspace_path / record["excerpt_path"]
        if not excerpt_path.is_file():
            issues.append(
                SourceIssue(
                    "SOURCE_EXCERPT_MISSING",
                    record["excerpt_path"],
                    f"{source_id} points at a missing excerpt file",
                )
            )
            continue
        try:
            excerpt_text = excerpt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(
                SourceIssue(
                    "SOURCE_INDEX_MALFORMED",
                    record["excerpt_path"],
                    f"{source_id} excerpt cannot be read as UTF-8 text: {exc}",
                )
            )
            continue
        if excerpt_sha256(excerpt_text) != digest:
            issues.append(
                SourceIssue(
                    "SOURCE_INDEX_MALFORMED",
                    record["excerpt_path"],
                    f"{source_id} sha256 does not match excerpt contents",
                )
            )
    referenced = {record["excerpt_path"] for record in records}
    sources_dir = workspace_path / SOURCES_DIRNAME
    if sources_dir.is_dir():
        for path in sorted(sources_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace_path).as_posix()
            if relative not in referenced:
                warnings.append(
                    SourceIssue(
                        "SOURCE_EXCERPT_UNREGISTERED",
                        relative,
                        "file in sources/ has no index record",
                    )
                )
    return SourceCacheEvaluation(tuple(records), tuple(issues), tuple(warnings))


def registered_source_ids(workspace: str | Path) -> frozenset[str]:
    evaluation = evaluate_index(workspace)
    if evaluation.issues:
        return frozenset()
    return frozenset(str(record["source_id"]) for record in evaluation.records)


def has_registered_source_id_reference(workspace: str | Path, text: str) -> bool:
    cited = set(source_ids_in_text(text))
    if not cited:
        return False
    return bool(cited & registered_source_ids(workspace))


@dataclass(frozen=True)
class AddResult:
    source_id: str
    created: bool
    url_duplicates: tuple[str, ...]


def add_source(
    workspace: str | Path,
    *,
    url: str,
    title: str,
    retrieved: str,
    grade: str,
    excerpt_text: str,
) -> AddResult:
    """Append one archived source. The only mutation path (main thread only).

    Append-only by construction: the index is opened in append mode, an
    existing excerpt file is never overwritten, and identical content
    (newline-normalized sha256) returns the existing source id instead of
    writing anything.
    """
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise SourceCacheError(f"workspace does not exist: {workspace_path}")
    for label, value in (("url", url), ("title", title)):
        if not str(value).strip():
            raise SourceCacheError(f"{label} must be non-empty")
        if _has_control_character(str(value)):
            raise SourceCacheError(f"{label} must be single-line text without control characters")
    if grade not in GRADES:
        raise SourceCacheError(f"grade must be one of: {', '.join(GRADES)}")
    try:
        datetime.strptime(retrieved, DATE_FORMAT)
    except ValueError as exc:
        raise SourceCacheError("retrieved must be YYYY-MM-DD") from exc
    normalized = normalize_excerpt_text(excerpt_text)
    if not normalized.strip():
        raise SourceCacheError("excerpt is empty")
    if len(normalized) > EXCERPT_MAX_CHARS:
        raise SourceCacheError(
            f"excerpt is {len(normalized)} characters; the cap is {EXCERPT_MAX_CHARS} "
            "(bounded key excerpts only — split the document into multiple sources)"
        )
    digest = excerpt_sha256(normalized)

    existing = evaluate_index(workspace_path)
    if existing.issues:
        details = "; ".join(
            f"{issue.code} at {issue.location}: {issue.message}" for issue in existing.issues
        )
        raise SourceCacheError(f"{SOURCE_INDEX_FILENAME} failed validation; refusing to append: {details}")
    records = list(existing.records)
    for record in records:
        if record.get("sha256") == digest and record.get("source_id"):
            return AddResult(str(record["source_id"]), False, ())
    url_duplicates = tuple(
        str(record["source_id"])
        for record in records
        if record.get("url") == url and record.get("source_id")
    )
    numbers = [parse_source_number(str(record.get("source_id", ""))) for record in records]
    next_number = 1 + max((number for number in numbers if number is not None), default=0)
    source_id = format_source_id(next_number)
    excerpt_relative = f"{SOURCES_DIRNAME}/{source_id}.md"
    excerpt_absolute = workspace_path / SOURCES_DIRNAME / f"{source_id}.md"
    if excerpt_absolute.exists():
        raise SourceCacheError(f"refusing to overwrite existing excerpt {excerpt_relative}")
    excerpt_absolute.parent.mkdir(parents=True, exist_ok=True)
    excerpt_absolute.write_text(normalized, encoding="utf-8")
    record = {
        "source_id": source_id,
        "url": url,
        "title": title,
        "retrieved": retrieved,
        "grade": grade,
        "excerpt_path": excerpt_relative,
        "sha256": digest,
    }
    try:
        with open(index_path(workspace_path), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        if excerpt_absolute.exists():
            excerpt_absolute.unlink()
        raise SourceCacheError(f"failed to append {SOURCE_INDEX_FILENAME}: {exc}") from exc
    return AddResult(source_id, True, url_duplicates)
