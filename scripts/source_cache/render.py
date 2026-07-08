from __future__ import annotations

from pathlib import Path

try:
    from .model import BIBLIOGRAPHY_HEADING, SOURCE_INDEX_FILENAME, SourceCacheError
    from .store import evaluate_index
except ImportError:
    from model import BIBLIOGRAPHY_HEADING, SOURCE_INDEX_FILENAME, SourceCacheError
    from store import evaluate_index


def render_source_bibliography(workspace: str | Path) -> str:
    """Render the dispatch-attachable bibliographic index.

    Identifiers only — source id, title, URL, retrieval date. Never excerpt
    content, grades, or interpretations. Empty string when nothing is
    archived; loud on a malformed or invalid index (attaching a bad index
    silently would hide a hand edit).
    """
    evaluation = evaluate_index(workspace)
    if evaluation.issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in evaluation.issues)
        raise SourceCacheError(f"{SOURCE_INDEX_FILENAME} failed validation: {details}")
    if not evaluation.records:
        return ""
    lines = [BIBLIOGRAPHY_HEADING, ""]
    for record in evaluation.records:
        lines.append(
            f"- {record['source_id']} | {record['title']} | {record['url']} | retrieved {record['retrieved']}"
        )
    return "\n".join(lines) + "\n"
