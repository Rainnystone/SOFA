"""Deterministic worker dispatch assembly.

Composes a complete dispatch text from the curated prompt template named by
worker_role_catalog, the main-thread-authored input, catalog slot facts, and
optional machine-trace attachments. Composition only: the assembler fills
declared slots and path tokens, never authors or rewrites prompt prose, never
writes workspace files, never appends to dispatch_log.jsonl, and never
dispatches.

Fill order is load-bearing: replace-slot literals contain the raw
`{WORKSPACE}` token, so slots are filled on the raw template body first and
path tokens are substituted afterwards.

Imports follow the PR #12 package/flat dual convention so that both
`import scripts.dispatch_assembly` from the repo root and flat imports with
`scripts/` on sys.path work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from ..worker_role_catalog import (
        WorkerRole,
        forbidden_input_violations,
        normalize_relative_path,
        normalize_role_slug,
        role_for_slug,
    )
    from ..capability_policy import (
        build_prior_query_digest,
        render_prior_query_digest,
    )
    from ..source_cache import SOURCE_INDEX_FILENAME, render_source_bibliography
except ImportError:
    from worker_role_catalog import (
        WorkerRole,
        forbidden_input_violations,
        normalize_relative_path,
        normalize_role_slug,
        role_for_slug,
    )
    from capability_policy import (
        build_prior_query_digest,
        render_prior_query_digest,
    )
    from source_cache import SOURCE_INDEX_FILENAME, render_source_bibliography


PLACEHOLDERS_HEADING = "\n## Placeholders"
NAME_FIELD_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


class AssemblyError(ValueError):
    """Raised when a dispatch cannot be assembled safely."""


@dataclass
class AssembledDispatch:
    role_slug: str
    prompt_template: str
    delivery_path: str
    delivery_abs_path: str
    dispatch_text: str
    attachments: list[str] = field(default_factory=list)
    suggested_record_fields: dict = field(default_factory=dict)


def primary_input_slot_name(role: str) -> str:
    worker = role_for_slug(normalize_role_slug(role))
    for slot in worker.dispatch_slots:
        if slot.name != "delivery_path":
            return slot.name
    raise AssemblyError(f"role {worker.slug} declares no input slot")


def assemble_dispatch(
    repo_root: Path | str,
    workspace: Path | str,
    role: str,
    slot_values: dict[str, str],
    name_fields: dict[str, str] | None = None,
    attach_digest: bool = True,
    attach_sources: bool = True,
    out_path: str | None = None,
) -> AssembledDispatch:
    repo_root_path = Path(repo_root)
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        raise AssemblyError(f"workspace does not exist: {workspace_path}")

    worker = role_for_slug(normalize_role_slug(role))
    template_path = worker.prompt_path(repo_root_path)
    if not template_path.is_file():
        raise AssemblyError(f"prompt template missing: {worker.prompt_template}")

    fields = {key: str(value) for key, value in (name_fields or {}).items()}
    for key, value in fields.items():
        if not NAME_FIELD_PATTERN.fullmatch(value):
            raise AssemblyError(f"name field {key} has an unsafe value: {value!r}")

    if out_path:
        try:
            delivery_rel = normalize_relative_path(out_path)
        except ValueError as exc:
            raise AssemblyError(
                f"out_path is not a safe workspace-relative path: {out_path!r} ({exc})"
            ) from exc
        if "{" in delivery_rel or "}" in delivery_rel:
            raise AssemblyError(f"out_path must not contain path tokens: {out_path!r}")
        if not worker.matches_delivery_path(delivery_rel):
            raise AssemblyError(
                f"out_path {delivery_rel!r} is outside the {worker.slug} delivery folder "
                f"{worker.delivery_folder!r}; sofa_contract would reject the record"
            )
    else:
        delivery_rel = _render_delivery_path(worker, fields)
    delivery_abs = str(workspace_path / delivery_rel)
    delivery_instruction = f"完成后用 Write 工具将完整输出写入 {delivery_abs}"

    _screen_inputs(worker, slot_values)

    body = template_path.read_text(encoding="utf-8").split(PLACEHOLDERS_HEADING, 1)[0]
    text = body.rstrip() + "\n"

    for slot in worker.dispatch_slots:
        if slot.name == "delivery_path":
            value = delivery_instruction
        else:
            value = slot_values.get(slot.name)
        if value is None:
            if slot.required:
                raise AssemblyError(
                    f"missing required slot value: {slot.name} for role {worker.slug}"
                )
            continue
        if "{PLUGIN_DIR}" in value or "{WORKSPACE}" in value:
            raise AssemblyError(
                f"slot {slot.name} value for role {worker.slug} must not contain "
                f"path tokens ({{PLUGIN_DIR}}/{{WORKSPACE}})"
            )
        if slot.style == "replace":
            if slot.literal not in text:
                raise AssemblyError(
                    f"slot literal for {slot.name} not found in template body of {worker.slug}"
                )
            text = text.replace(slot.literal, value)
        else:
            text = text.rstrip() + f"\n\n{slot.heading}\n\n{value}\n"

    for slot in worker.dispatch_slots:
        if slot.style == "replace" and slot.literal in text:
            raise AssemblyError(
                f"slot literal for {slot.name} was not filled in role {worker.slug}"
            )

    text = text.replace("{PLUGIN_DIR}", str(repo_root_path))
    text = text.replace("{WORKSPACE}", str(workspace_path))
    if "{PLUGIN_DIR}" in text or "{WORKSPACE}" in text:
        raise AssemblyError("path tokens remain after substitution")

    attachments: list[str] = []
    if attach_digest and (workspace_path / "search_log.jsonl").exists():
        try:
            digest_text = render_prior_query_digest(
                build_prior_query_digest(workspace_path)
            )
        except ValueError as exc:
            raise AssemblyError(f"prior-query digest failed: {exc}") from exc
        # The prior-query digest renders raw query text, which may carry
        # market-data or action-class language. Attaching it unscreened to an
        # isolated role would reintroduce the exact terms the packet screening
        # just blocked, so screen the rendered digest with the same role rules.
        digest_violations = forbidden_input_violations(worker, digest_text)
        if digest_violations:
            details = "; ".join(
                f"{issue.issue_code}: {issue.message}" for issue in digest_violations
            )
            raise AssemblyError(
                f"prior-query digest for role {worker.slug} failed input "
                f"screening: {details} (use --no-digest to dispatch without the digest)"
            )
        text = text.rstrip() + "\n\n" + digest_text
        attachments.append("prior_query_digest")

    if attach_sources and (workspace_path / SOURCE_INDEX_FILENAME).exists():
        try:
            bibliography_text = render_source_bibliography(workspace_path)
        except ValueError as exc:
            raise AssemblyError(f"source bibliography failed: {exc}") from exc
        if bibliography_text:
            # Titles are external text and may carry market-data or action
            # terms; attaching them unscreened would reintroduce exactly what
            # packet screening just blocked.
            bibliography_violations = forbidden_input_violations(worker, bibliography_text)
            if bibliography_violations:
                details = "; ".join(
                    f"{issue.issue_code}: {issue.message}" for issue in bibliography_violations
                )
                raise AssemblyError(
                    f"source bibliography for role {worker.slug} failed input "
                    f"screening: {details} (use --no-sources to dispatch without it)"
                )
            text = text.rstrip() + "\n\n" + bibliography_text
            attachments.append("source_bibliography")

    # suggested_record_fields is a partial dispatch_log.jsonl skeleton. The
    # assembler fills only what it can derive deterministically; the main
    # thread completes the record when the dispatch actually happens. loop_id
    # is contract-required on delivered records but cannot be derived for
    # roles whose filename template has no loop field (financial_bridge uses
    # {ticker}, red_team uses {round}); for those roles loop_id is None and is
    # flagged in incomplete_fields so the main thread binds the record to the
    # relevant loop instead of silently shipping an incomplete record that
    # sofa_contract will reject.
    suggested: dict = {"role": worker.slug, "delivery_path": delivery_rel}
    incomplete = ["dispatch_id", "mechanism", "status"]
    if "loop" in fields:
        suggested["loop_id"] = f"loop_{fields['loop']}"
    else:
        suggested["loop_id"] = None
        incomplete.insert(0, "loop_id")
    suggested["incomplete_fields"] = incomplete

    return AssembledDispatch(
        role_slug=worker.slug,
        prompt_template=worker.prompt_template,
        delivery_path=delivery_rel,
        delivery_abs_path=delivery_abs,
        dispatch_text=text,
        attachments=attachments,
        suggested_record_fields=suggested,
    )


def _render_delivery_path(worker: WorkerRole, fields: dict[str, str]) -> str:
    try:
        filename = worker.delivery_filename_template.format(**fields)
    except KeyError as exc:
        raise AssemblyError(
            f"missing delivery filename field {exc.args[0]!r} for role {worker.slug} "
            f"(template {worker.delivery_filename_template!r})"
        ) from exc
    return f"{worker.delivery_folder}/{filename}"


def _screen_inputs(worker: WorkerRole, slot_values: dict[str, str]) -> None:
    for name, value in slot_values.items():
        violations = forbidden_input_violations(worker, value)
        if violations:
            details = "; ".join(
                f"{issue.issue_code}: {issue.message}" for issue in violations
            )
            raise AssemblyError(
                f"slot {name} for role {worker.slug} failed input screening: {details}"
            )
