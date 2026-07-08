from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

SCHEMA_FIELDS = ("source_id", "url", "title", "retrieved", "grade", "excerpt_path", "sha256")
SOURCE_INDEX_FILENAME = "sources_index.jsonl"
SOURCES_DIRNAME = "sources"
GRADES = ("A", "B", "C", "D")
EXCERPT_MAX_CHARS = 16000
BIBLIOGRAPHY_HEADING = "### Prior Source Index (identifiers only)"
DATE_FORMAT = "%Y-%m-%d"

SOURCE_ID_PATTERN = re.compile(r"\bsrc-\d{3,}\b")
_SOURCE_ID_EXACT = re.compile(r"^src-\d{3,}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class SourceCacheError(ValueError):
    """Raised when the source cache cannot be read or mutated safely."""


@dataclass(frozen=True)
class SourceIssue:
    code: str
    location: str
    message: str


@dataclass(frozen=True)
class SourceCacheEvaluation:
    records: tuple[dict, ...]
    issues: tuple[SourceIssue, ...]
    warnings: tuple[SourceIssue, ...]


def normalize_excerpt_text(text: str) -> str:
    """Normalize newlines before hashing so dedupe is platform-stable."""
    return text.replace("\r\n", "\n")


def excerpt_sha256(text: str) -> str:
    return hashlib.sha256(normalize_excerpt_text(text).encode("utf-8")).hexdigest()


def source_ids_in_text(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0) for match in SOURCE_ID_PATTERN.finditer(text)))


def format_source_id(number: int) -> str:
    return f"src-{number:03d}"


def parse_source_number(source_id: str) -> int | None:
    if not _SOURCE_ID_EXACT.fullmatch(str(source_id)):
        return None
    return int(str(source_id).split("-", 1)[1])


def validate_record(record: dict, line_number: int) -> list[SourceIssue]:
    location = f"{SOURCE_INDEX_FILENAME}:{line_number}"
    issues: list[SourceIssue] = []
    keys = set(record)
    missing = [field for field in SCHEMA_FIELDS if field not in keys]
    unknown = sorted(keys - set(SCHEMA_FIELDS))
    if missing:
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, f"missing fields: {', '.join(missing)}"))
    if unknown:
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, f"unknown fields: {', '.join(unknown)}"))
    if issues:
        return issues
    for field in SCHEMA_FIELDS:
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, f"{field} must be a non-empty string"))
    if issues:
        return issues
    if parse_source_number(record["source_id"]) is None:
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, f"source_id {record['source_id']!r} is not src-NNN"))
    if record["grade"] not in GRADES:
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, f"grade must be one of: {', '.join(GRADES)}"))
    try:
        datetime.strptime(record["retrieved"], DATE_FORMAT)
    except ValueError:
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, "retrieved must be YYYY-MM-DD"))
    if not _SHA256_HEX.fullmatch(record["sha256"]):
        issues.append(SourceIssue("SOURCE_INDEX_MALFORMED", location, "sha256 must be 64 lowercase hex characters"))
    excerpt_path = record["excerpt_path"]
    parts = excerpt_path.split("/")
    if "\\" in excerpt_path or ".." in parts or parts[0] != SOURCES_DIRNAME or len(parts) < 2:
        issues.append(
            SourceIssue(
                "SOURCE_INDEX_MALFORMED",
                location,
                f"excerpt_path must be a POSIX path under {SOURCES_DIRNAME}/",
            )
        )
    return issues
