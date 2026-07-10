from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


VALID_MODES = ("ticker", "sector")


@dataclass(frozen=True)
class ArtifactSpec:
    path: str
    label: str
    kind: str


@dataclass(frozen=True)
class ManagedBlock:
    name: str
    heading: str
    start_marker: str
    end_marker: str


@dataclass(frozen=True)
class WorkspaceArtifactContract:
    mode: str
    common_directory_specs: tuple[ArtifactSpec, ...]
    mode_directory_specs: tuple[ArtifactSpec, ...]
    common_file_specs: tuple[ArtifactSpec, ...]
    mode_file_specs: tuple[ArtifactSpec, ...]
    machine_ledgers: tuple[str, ...]
    managed_blocks: tuple[ManagedBlock, ...]
    workflow_stage_markers: tuple[str, ...]
    worker_output_directories: tuple[str, ...]
    main_thread_artifacts: tuple[str, ...]

    @property
    def directory_specs(self) -> tuple[ArtifactSpec, ...]:
        return self.common_directory_specs + self.mode_directory_specs

    @property
    def file_specs(self) -> tuple[ArtifactSpec, ...]:
        return self.common_file_specs + self.mode_file_specs

    @property
    def common_directories(self) -> tuple[str, ...]:
        return tuple(spec.path for spec in self.common_directory_specs if spec.path != ".")

    @property
    def mode_directories(self) -> tuple[str, ...]:
        return tuple(spec.path for spec in self.mode_directory_specs)

    @property
    def common_files(self) -> tuple[str, ...]:
        return tuple(spec.path for spec in self.common_file_specs)

    @property
    def mode_artifacts(self) -> tuple[str, ...]:
        return tuple(spec.path for spec in self.mode_file_specs)

    def created_artifact_labels(self) -> tuple[str, ...]:
        return tuple(spec.label for spec in self.directory_specs + self.file_specs)

    def all_scaffold_paths(self) -> tuple[str, ...]:
        return tuple(
            spec.path
            for spec in self.directory_specs + self.file_specs
            if spec.path != "."
        )

    def resolve(self, workspace_root: str | Path, relative_path: str | Path) -> Path:
        normalized = _normalize_relative_path(relative_path)
        root = Path(workspace_root)
        if normalized == ".":
            return root
        return root / normalized

    def is_worker_output_path(self, relative_path: str | Path) -> bool:
        normalized = _normalize_relative_path(relative_path)
        if normalized in self.main_thread_artifacts:
            return False
        return any(
            normalized.startswith(f"{directory}/")
            for directory in self.worker_output_directories
        )


COMMON_DIRECTORY_SPECS = (
    ArtifactSpec(".", "./", "directory"),
    ArtifactSpec("scouts", "scouts/", "directory"),
    ArtifactSpec("challenges", "challenges/", "directory"),
    ArtifactSpec("maps", "maps/", "directory"),
    ArtifactSpec("financials", "financials/", "directory"),
    ArtifactSpec("redteam", "redteam/", "directory"),
    ArtifactSpec("reports", "reports/", "directory"),
    ArtifactSpec("dive_packets", "dive_packets/", "directory"),
    ArtifactSpec("sources", "sources/", "directory"),
)

SECTOR_DIRECTORY_SPECS = (
    ArtifactSpec("coverage", "coverage/", "directory"),
)

COMMON_FILE_SPECS = (
    ArtifactSpec("research_workflow.md", "research_workflow.md", "file"),
    ArtifactSpec("evidence_ledger.md", "evidence_ledger.md", "file"),
    ArtifactSpec("claim_ledger.md", "claim_ledger.md", "file"),
    ArtifactSpec("search_log.md", "search_log.md", "file"),
    ArtifactSpec("search_log.jsonl", "search_log.jsonl", "file"),
    ArtifactSpec("dispatch_log.jsonl", "dispatch_log.jsonl", "file"),
    ArtifactSpec("capability_report.md", "capability_report.md", "file"),
    ArtifactSpec("state.json", "state.json", "file"),
    ArtifactSpec("frontier_registry.json", "frontier_registry.json", "file"),
    ArtifactSpec("framing_contract.json", "framing_contract.json", "file"),
    ArtifactSpec("sources_index.jsonl", "sources_index.jsonl", "file"),
)

SECTOR_FILE_SPECS = (
    ArtifactSpec("maps/dependency_ladder.md", "maps/dependency_ladder.md", "file"),
)

MACHINE_LEDGERS = (
    "framing_contract.json",
    "search_log.jsonl",
    "dispatch_log.jsonl",
    "state.json",
    "frontier_registry.json",
    "sources_index.jsonl",
)

CORE_REQUIRED_FILES = (
    "state.json",
    "research_workflow.md",
    "evidence_ledger.md",
)

MANAGED_BLOCKS = (
    ManagedBlock(
        name="framing-contract",
        heading="Framing Intent Contract",
        start_marker="<!-- SOFA:framing-contract:start -->",
        end_marker="<!-- SOFA:framing-contract:end -->",
    ),
    ManagedBlock(
        name="frontier-review-log",
        heading="Frontier Review Log",
        start_marker="<!-- SOFA:frontier-review-log:start -->",
        end_marker="<!-- SOFA:frontier-review-log:end -->",
    ),
    ManagedBlock(
        name="frontier-discovery-log",
        heading="Frontier Discovery Log",
        start_marker="<!-- SOFA:frontier-discovery-log:start -->",
        end_marker="<!-- SOFA:frontier-discovery-log:end -->",
    ),
    ManagedBlock(
        name="frontier-layer-coverage",
        heading="Frontier Layer Coverage",
        start_marker="<!-- SOFA:frontier-layer-coverage:start -->",
        end_marker="<!-- SOFA:frontier-layer-coverage:end -->",
    ),
)

TICKER_WORKFLOW_STAGE_MARKERS = (
    "Stage 0: Intake + Framing",
    "Stage 1: Provisional Frontier Plan",
    "Stage 2: Evidence Frontier Loops",
    "Stage 3: Thesis + Financial Bridge",
    "Stage 4: Formal Red Team",
    "Stage 5: Final Verdict",
    "Stage 6: Watch Protocol",
)

SECTOR_WORKFLOW_STAGE_MARKERS = (
    "Stage 0: Intake + Framing",
    "Stage 1: Provisional Frontier Plan",
    "Stage 2: Mapping Loops",
    "Stage 3: Chokepoint Scoring + Financial Screen",
    "Stage 4: Mapping Integrity Review",
    "Stage 5: Ranked Target Queue",
    "Stage 6: Watch Protocol",
)

TICKER_WORKER_OUTPUT_DIRECTORIES = (
    "scouts",
    "challenges",
    "maps",
    "financials",
    "redteam",
)

SECTOR_WORKER_OUTPUT_DIRECTORIES = (
    "maps",
    "coverage",
    "financials",
    "redteam",
)

ALL_WORKER_OUTPUT_DIRECTORIES = (
    "scouts",
    "challenges",
    "maps",
    "coverage",
    "financials",
    "redteam",
)

MAIN_THREAD_ARTIFACTS = (
    "maps/dependency_ladder.md",
)


def normalize_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError(f"Unsupported SOFA workspace mode: {mode!r}")
    return normalized


def artifact_contract_for_mode(mode: str) -> WorkspaceArtifactContract:
    normalized = normalize_mode(mode)
    if normalized == "sector":
        return WorkspaceArtifactContract(
            mode="sector",
            common_directory_specs=COMMON_DIRECTORY_SPECS,
            mode_directory_specs=SECTOR_DIRECTORY_SPECS,
            common_file_specs=COMMON_FILE_SPECS,
            mode_file_specs=SECTOR_FILE_SPECS,
            machine_ledgers=MACHINE_LEDGERS,
            managed_blocks=MANAGED_BLOCKS,
            workflow_stage_markers=SECTOR_WORKFLOW_STAGE_MARKERS,
            worker_output_directories=SECTOR_WORKER_OUTPUT_DIRECTORIES,
            main_thread_artifacts=MAIN_THREAD_ARTIFACTS,
        )
    return WorkspaceArtifactContract(
        mode="ticker",
        common_directory_specs=COMMON_DIRECTORY_SPECS,
        mode_directory_specs=(),
        common_file_specs=COMMON_FILE_SPECS,
        mode_file_specs=(),
        machine_ledgers=MACHINE_LEDGERS,
        managed_blocks=MANAGED_BLOCKS,
        workflow_stage_markers=TICKER_WORKFLOW_STAGE_MARKERS,
        worker_output_directories=TICKER_WORKER_OUTPUT_DIRECTORIES,
        main_thread_artifacts=MAIN_THREAD_ARTIFACTS,
    )


def all_worker_output_directories() -> tuple[str, ...]:
    return ALL_WORKER_OUTPUT_DIRECTORIES


def core_required_files() -> tuple[str, ...]:
    return CORE_REQUIRED_FILES


def is_main_thread_artifact(relative_path: str | Path) -> bool:
    return _normalize_relative_path(relative_path) in MAIN_THREAD_ARTIFACTS


def managed_block_for_name(name: str) -> ManagedBlock:
    """Return the registered ManagedBlock for a block name.

    O(n) lookup over the tuple. Raises ValueError for an unknown name so
    callers fail loudly rather than silently no-op.
    """
    for block in MANAGED_BLOCKS:
        if block.name == name:
            return block
    raise ValueError(f"Unknown managed block: {name!r}")


def replace_managed_block(text: str, block_name: str, replacement: str) -> str:
    """Replace one named managed Markdown block by its registered markers.

    Consumes the ManagedBlock data markers (no f-string re-derivation, which
    was the marker double-source this migration kills). Preserves the
    duplicate-marker and misordered-marker validation the frontier_lifecycle
    version provided: exactly one start marker and exactly one end marker,
    start before end.
    """
    block = managed_block_for_name(block_name)
    begin = block.start_marker
    end = block.end_marker

    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count == 0:
        raise ValueError(f"managed block {block_name!r} has no start marker")
    if end_count == 0:
        raise ValueError(f"managed block {block_name!r} has no end marker")
    if begin_count != 1:
        raise ValueError(f"managed block {block_name!r} must have exactly one start marker")
    if end_count != 1:
        raise ValueError(f"managed block {block_name!r} must have exactly one end marker")

    start = text.find(begin)
    stop = text.find(end)
    if start > stop:
        raise ValueError(f"managed block {block_name!r} end marker appears before start marker")

    block_text = f"{begin}\n{replacement.rstrip()}\n{end}"
    return f"{text[:start]}{block_text}{text[stop + len(end):]}"


def _render_registered_managed_block(
    block: ManagedBlock,
    replacement: str,
) -> str:
    body = replacement.rstrip("\n")
    if body:
        body += "\n"
    return (
        f"## {block.heading}\n"
        f"{block.start_marker}\n"
        f"{body}"
        f"{block.end_marker}"
    )


def upsert_managed_block_after(
    text: str,
    block_name: str,
    replacement: str,
    *,
    after_block_name: str,
) -> str:
    """Replace or insert one registered block after a registered anchor."""
    block = managed_block_for_name(block_name)
    anchor = managed_block_for_name(after_block_name)

    anchor_start_count = text.count(anchor.start_marker)
    anchor_end_count = text.count(anchor.end_marker)
    if anchor_start_count != 1:
        raise ValueError(
            f"managed block {after_block_name!r} must have exactly one start marker"
        )
    if anchor_end_count != 1:
        raise ValueError(
            f"managed block {after_block_name!r} must have exactly one end marker"
        )

    anchor_start = text.find(anchor.start_marker)
    anchor_end = text.find(anchor.end_marker)
    if anchor_start > anchor_end:
        raise ValueError(
            f"managed block {after_block_name!r} end marker appears before start marker"
        )

    target_start_count = text.count(block.start_marker)
    target_end_count = text.count(block.end_marker)
    if target_start_count == 0 and target_end_count == 0:
        insertion_point = anchor_end + len(anchor.end_marker)
        suffix = text[insertion_point:].lstrip("\r\n")
        rendered = _render_registered_managed_block(block, replacement)
        return f"{text[:insertion_point]}\n\n{rendered}\n\n{suffix}"

    if target_start_count != 1:
        raise ValueError(
            f"managed block {block_name!r} must have exactly one start marker"
        )
    if target_end_count != 1:
        raise ValueError(
            f"managed block {block_name!r} must have exactly one end marker"
        )

    target_start = text.find(block.start_marker)
    target_end = text.find(block.end_marker)
    if target_start > target_end:
        raise ValueError(
            f"managed block {block_name!r} end marker appears before start marker"
        )
    if target_start <= anchor_end:
        raise ValueError(
            f"managed block {block_name!r} must appear after {after_block_name!r}"
        )

    return replace_managed_block(text, block_name, replacement)


def _normalize_relative_path(relative_path: str | Path) -> str:
    raw_text = str(relative_path)
    raw_path = Path(raw_text)
    windows_path = PureWindowsPath(raw_text)
    if raw_path.is_absolute() or windows_path.drive or windows_path.root:
        raise ValueError(
            f"Expected workspace-relative path, got absolute path: {relative_path!r}"
        )

    raw = raw_text.replace("\\", "/")
    if raw in {"", "."}:
        return "."

    normalized_parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized_parts:
                raise ValueError(
                    "Expected workspace-relative path, "
                    f"got path outside workspace: {relative_path!r}"
                )
            normalized_parts.pop()
            continue
        normalized_parts.append(part)

    if not normalized_parts:
        return "."
    return "/".join(normalized_parts)
