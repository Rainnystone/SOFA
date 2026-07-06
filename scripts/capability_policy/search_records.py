"""Read-only search-record digests for SOFA capability policy outputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from frontier_lifecycle import LOOP_HEADER_RE

from .policy import STAGE0_LOOP_ID


DIGEST_HEADING = "### Prior Search Trace (negative trace only)"
STATS_HEADING = "### Search Yield Statistics (advisory only)"

_LOOP_ID_RE = re.compile(r"^loop_([1-9][0-9]*)$")
_UNBOUND = "unbound"
_ALLOWED_RECORD_FIELDS = (
    "loop_id",
    "dispatch_id",
    "result_status",
    "query",
    "dead_ends",
    "evidence_refs",
)


@dataclass(frozen=True)
class DeadEnd:
    query: str
    category: str


@dataclass
class DigestGroup:
    group_id: str
    loop_keys: list[str]
    queries: list[str]
    dead_ends: list[DeadEnd]
    visited_hosts: list[str]
    source_identifiers: list[str]


@dataclass
class LoopYieldStats:
    loop_key: str
    record_count: int
    distinct_queries: int
    dead_end_counts: dict[str, int]
    dead_end_rate: float
    unique_refs: int
    first_seen_refs: int


def build_prior_query_digest(workspace: Path | str) -> list[DigestGroup]:
    workspace_path = _require_workspace(workspace)
    loop_map = _read_ledger_loop_map(workspace_path)
    groups: dict[str, DigestGroup] = {}

    for record in _iter_records(workspace_path):
        loop_key = _loop_key(record)
        group_id = _group_id_for_record(loop_key, loop_map)
        group = groups.setdefault(
            group_id,
            DigestGroup(
                group_id=group_id,
                loop_keys=[],
                queries=[],
                dead_ends=[],
                visited_hosts=[],
                source_identifiers=[],
            ),
        )

        _append_unique(group.loop_keys, loop_key)
        query = _string_value(record.get("query"))
        if query:
            _append_unique(group.queries, query)

        for dead_end in _dead_ends(record):
            _append_unique(group.dead_ends, dead_end)

        for ref in _evidence_refs(record):
            parsed = urlparse(ref)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                _append_unique(group.visited_hosts, parsed.hostname)
            else:
                _append_unique(group.source_identifiers, ref)

    return sorted(groups.values(), key=lambda group: _group_sort_key(group.group_id))


def render_prior_query_digest(groups: list[DigestGroup]) -> str:
    lines = [DIGEST_HEADING]
    if not groups:
        lines.append("")
        lines.append("(no recorded searches)")
        return "\n".join(lines)

    for group in groups:
        lines.append("")
        lines.append(f"#### {group.group_id}")
        if group.loop_keys:
            lines.append(f"Loops: {', '.join(group.loop_keys)}")
        if group.queries:
            lines.append("Queries:")
            lines.extend(f"- {query}" for query in group.queries)
        if group.dead_ends:
            lines.append("Dead ends:")
            lines.extend(
                f"  - [{dead_end.category}] {dead_end.query}"
                for dead_end in group.dead_ends
            )
        if group.visited_hosts:
            lines.append("Visited hosts:")
            lines.extend(f"- {host}" for host in group.visited_hosts)
        if group.source_identifiers:
            lines.append("Source identifiers:")
            lines.extend(f"- {identifier}" for identifier in group.source_identifiers)

    return "\n".join(lines)


def build_search_yield_stats(workspace: Path | str) -> list[LoopYieldStats]:
    workspace_path = _require_workspace(workspace)
    records_by_loop: dict[str, list[dict[str, object]]] = {}

    for record in _iter_records(workspace_path):
        loop_key = _loop_key(record)
        records_by_loop.setdefault(loop_key, []).append(record)

    seen_refs: set[str] = set()
    stats: list[LoopYieldStats] = []
    for loop_key in sorted(records_by_loop, key=_loop_sort_key):
        records = records_by_loop[loop_key]
        queries: list[str] = []
        refs: list[str] = []
        dead_ends: list[DeadEnd] = []
        dead_end_counts: dict[str, int] = {}

        for record in records:
            query = _string_value(record.get("query"))
            if query:
                _append_unique(queries, query)
            for dead_end in _dead_ends(record):
                dead_ends.append(dead_end)
            for ref in _evidence_refs(record):
                _append_unique(refs, ref)

        for dead_end in dead_ends:
            dead_end_counts[dead_end.category] = (
                dead_end_counts.get(dead_end.category, 0) + 1
            )

        new_refs = [ref for ref in refs if ref not in seen_refs]
        seen_refs.update(refs)
        distinct_queries = len(queries)
        stats.append(
            LoopYieldStats(
                loop_key=loop_key,
                record_count=len(records),
                distinct_queries=distinct_queries,
                dead_end_counts=dead_end_counts,
                dead_end_rate=len(dead_ends) / max(distinct_queries, 1),
                unique_refs=len(refs),
                first_seen_refs=len(new_refs),
            )
        )

    return stats


def render_search_yield_stats(stats: list[LoopYieldStats]) -> str:
    lines = [
        STATS_HEADING,
        "",
        "Advisory search-yield signals only.",
        "",
        "| Loop | Records | Distinct queries | Dead ends | Dead-end rate | Unique refs | First-seen refs |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    if not stats:
        lines.append("| (no records) | 0 | 0 | 0 (-) | 0.00 | 0 | 0 |")
        return "\n".join(lines)

    for entry in stats:
        dead_end_total = sum(entry.dead_end_counts.values())
        categories = _render_dead_end_counts(entry.dead_end_counts)
        lines.append(
            f"| {entry.loop_key} | {entry.record_count} | "
            f"{entry.distinct_queries} | {dead_end_total} ({categories}) | "
            f"{entry.dead_end_rate:.2f} | {entry.unique_refs} | "
            f"{entry.first_seen_refs} |"
        )

    return "\n".join(lines)


def _require_workspace(workspace: Path | str) -> Path:
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise ValueError(f"workspace path is not a directory: {workspace_path}")
    return workspace_path


def _iter_records(workspace: Path) -> list[dict[str, object]]:
    log_path = workspace / "search_log.jsonl"
    if not log_path.exists():
        return []

    records: list[dict[str, object]] = []
    with log_path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                parsed = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"malformed JSON in search_log.jsonl line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"search_log.jsonl line {line_number} is not a JSON object"
                )
            records.append(
                {
                    field: parsed.get(field)
                    for field in _ALLOWED_RECORD_FIELDS
                    if field in parsed
                }
            )
    return records


def _read_ledger_loop_map(workspace: Path) -> dict[str, str]:
    ledger_path = workspace / "evidence_ledger.md"
    if not ledger_path.exists():
        return {}

    loop_map: dict[str, str] = {}
    for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
        match = LOOP_HEADER_RE.fullmatch(raw_line.rstrip())
        if match is not None:
            loop_map[match.group("loop")] = match.group("frontier_id")
    return loop_map


def _loop_key(record: dict[str, object]) -> str:
    loop_id = _string_value(record.get("loop_id"))
    if loop_id == STAGE0_LOOP_ID:
        return STAGE0_LOOP_ID
    if loop_id and _LOOP_ID_RE.fullmatch(loop_id):
        return loop_id
    return _UNBOUND


def _group_id_for_record(loop_key: str, loop_map: dict[str, str]) -> str:
    if loop_key == STAGE0_LOOP_ID:
        return STAGE0_LOOP_ID
    match = _LOOP_ID_RE.fullmatch(loop_key)
    if match is None:
        return _UNBOUND
    return loop_map.get(match.group(1), _UNBOUND)


def _dead_ends(record: dict[str, object]) -> list[DeadEnd]:
    raw_dead_ends = record.get("dead_ends")
    if not isinstance(raw_dead_ends, list):
        return []

    dead_ends: list[DeadEnd] = []
    for raw_entry in raw_dead_ends:
        if not isinstance(raw_entry, dict):
            continue
        query = _string_value(raw_entry.get("query"))
        category = _string_value(raw_entry.get("category"))
        if query and category:
            dead_ends.append(DeadEnd(query=query, category=category))
    return dead_ends


def _evidence_refs(record: dict[str, object]) -> list[str]:
    raw_refs = record.get("evidence_refs")
    if not isinstance(raw_refs, list):
        return []

    refs: list[str] = []
    for raw_ref in raw_refs:
        ref = _string_value(raw_ref)
        if ref:
            _append_unique(refs, ref)
    return refs


def _string_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _append_unique(items: list, item: object) -> None:
    if item not in items:
        items.append(item)


def _group_sort_key(group_id: str) -> tuple[int, int, str]:
    if group_id == STAGE0_LOOP_ID:
        return (0, 0, group_id)
    if group_id == _UNBOUND:
        return (2, 0, group_id)
    frontier_match = re.fullmatch(r"F([1-9][0-9]*)", group_id)
    if frontier_match is not None:
        return (1, int(frontier_match.group(1)), group_id)
    return (1, 10**12, group_id)


def _loop_sort_key(loop_key: str) -> tuple[int, int, str]:
    if loop_key == STAGE0_LOOP_ID:
        return (0, 0, loop_key)
    if loop_key == _UNBOUND:
        return (2, 0, loop_key)
    loop_match = _LOOP_ID_RE.fullmatch(loop_key)
    if loop_match is not None:
        return (1, int(loop_match.group(1)), loop_key)
    return (2, 1, loop_key)


def _render_dead_end_counts(dead_end_counts: dict[str, int]) -> str:
    if not dead_end_counts:
        return "-"
    return ", ".join(
        f"{category}: {count}" for category, count in dead_end_counts.items()
    )
