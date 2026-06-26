from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
)

SECTOR_FILE_SPECS = (
    ArtifactSpec("maps/dependency_ladder.md", "maps/dependency_ladder.md", "file"),
)

MACHINE_LEDGERS = (
    "search_log.jsonl",
    "dispatch_log.jsonl",
    "state.json",
    "frontier_registry.json",
)

CORE_REQUIRED_FILES = (
    "state.json",
    "research_workflow.md",
    "evidence_ledger.md",
)

MANAGED_BLOCKS = (
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


def _normalize_relative_path(relative_path: str | Path) -> str:
    raw = Path(str(relative_path)).as_posix()
    while raw.startswith("./"):
        raw = raw[2:]
    if raw in {"", "."}:
        return "."
    return raw
