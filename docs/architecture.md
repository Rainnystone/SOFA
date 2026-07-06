# Architecture

SOFA is a host-neutral research harness. It is not one large prompt and not a single host-agent integration. The core repo defines research workflow, durable workspace state, deterministic validation, and reusable worker methods. Host-specific behavior stays in adapters.

## Design Principles

| Principle | Meaning |
|-----------|---------|
| Host-neutral core | Core guides, method cards, prompts, scripts, and tests avoid depending on one agent runtime or one tool name. |
| Durable workspace | Research state lives in files that can be reviewed, resumed, challenged, and tested. |
| Deterministic gates | Validation, schema checks, path checks, lifecycle legality, and report gates are handled by scripts. |
| Agent judgment boundary | Evidence interpretation, frontier decisions, and final research judgment remain with the main analyst thread. |
| Progressive disclosure | The entry skill routes the work; mode guides, method cards, prompts, and references are loaded only when needed. |
| Audit before polish | A readable report is allowed only after evidence, claim, challenge, and lifecycle trails exist. |

## System Layers

| Layer | Primary files | Responsibility |
|-------|---------------|----------------|
| Entry router | `skills/sofa-analyze/SKILL.md` | Classify the user's request and route to Ticker Dive, Sector Hunt, or Sector-to-Ultra. |
| Mode guides | `skills/sofa-analyze/references/*-guide.md` | Define the stage sequence, loop rhythm, required artifacts, and mode-specific constraints. |
| Method cards | `skills/sofa-analyze/method-cards/*/METHOD.md` | Provide private worker methods for mapping, customer discovery, financial bridge, and red-team analysis. |
| Prompt templates | `scripts/prompts/*.md` | Give worker agents bounded instructions for scout, challenge, mapper, review, and red-team tasks. |
| Deterministic scripts and contracts | `scripts/*.py`, `scripts/sofa_contract/`, `scripts/workspace_contract/`, `scripts/worker_role_catalog/` | Initialize workspaces, own deterministic workspace and worker-role facts, enforce lifecycle and stage gates, validate reports, and create Ultra packets. |
| Documentation | `docs/*.md`, `docs/adapters/*.md` | Explain setup, capabilities, architecture, repo navigation, reports, and host mappings. |
| Tests | `tests/test_*.py` | Lock down repo structure, workspace initialization, lifecycle rules, CLI behavior, and gates. |

## Main Control Flow

```text
User research request
  -> SOFA Analyze router
  -> mode guide selection
  -> workspace initialization
  -> Stage 0 framing
  -> Stage 1 frontier plan
  -> Stage 2 evidence / mapping loops
       -> worker products
       -> evidence and claim ledgers
       -> frontier lifecycle review
       -> deterministic gate checks
  -> Stage 3 thesis / scoring / red team
  -> final report and watch protocol
```

Ticker Dive and Sector Hunt share the same harness shape but enforce different outputs. Ticker Dive can eventually produce action-class language after the financial bridge and formal red team. Sector Hunt stops at a dependency map and ranked queue; any action-class work must continue through Ticker Dive or Ultra Dive.

## Workspace State

A SOFA workspace is the durable research ledger. The important files are:

| Workspace file | Role |
|----------------|------|
| `state.json` | Coarse workspace mode and stage state. It is not the source of truth for per-frontier loop counts. |
| `frontier_registry.json` | Machine-readable frontier lifecycle state: IDs, status, source, lifecycle history, review decisions, and limits. |
| `research_workflow.md` | Human-readable stage log, decision log, and managed Frontier Review / Discovery blocks. |
| `evidence_ledger.md` | Evidence loop record. Stable headers like `## Loop N: F{id} - {name}` are the source of truth for per-frontier loop counts. |
| `claim_ledger.md` | Important claims, status, evidence grade, and unresolved gaps. |
| `search_log.md` | Human-readable mirror for search trail and capability limitations. |
| `search_log.jsonl` | Machine-readable authority for completed or approved degraded search records. |
| `dispatch_log.jsonl` | Machine-readable authority for delivered subagent dispatch and approved degraded-mode delivery proof. |
| worker output folders | Scout, challenge, mapper, coverage, financial bridge, red-team, and review products. |

The architecture intentionally keeps machine constraints and human narration separate: JSON carries lifecycle state; Markdown carries reviewable reasoning and evidence trails.

The workspace artifact inventory and worker-output path classification are defined in `scripts/workspace_contract/`. Setup scripts and validators consume that contract instead of copying folder, ledger, managed-block, or scaffold lists into separate rule tables.

`scripts/worker_role_catalog/` is the deterministic source for worker role facts. Human-readable role tables in the entry skill and dispatch guide summarize those facts for operators, while validators consume the catalog for role-specific worker-output and dispatch checks.

`scripts/capability_policy/` is the deterministic source for capability facts. `capability_check.py` and `init_workspace.py` render capability text from it, and `sofa_contract` consumes its search-record status vocabulary.

## Frontier Lifecycle Architecture

Frontiers are first-class research objects. Stage 1 proposes the initial set, but Stage 2 can add, start, continue, retire, reprioritize, and reactivate them through the lifecycle CLI.

```text
evidence_ledger.md
  -> derive loop counts from stable F{id} headers
  -> check whether Active frontiers crossed an unrecorded review boundary
  -> record Continued or Retired decisions
  -> update frontier_registry.json
  -> render managed review/discovery logs into research_workflow.md
  -> gate_check.py blocks Stage 3 until no Active or New frontier remains
```

The review trigger is boundary-window based: a frontier is review-due when `derived_loop_count // every_loops > review_count` and `review_count < max_reviews`. Counts 3, 6, and 9 open review windows; if the main thread overshoots to loop 4 or 5 without recording the review, the frontier remains due until the review is recorded.

## Deterministic Boundary

Scripts enforce rules that should not depend on agent memory:

| Script | Deterministic responsibility |
|--------|------------------------------|
| `init_workspace.py` | Create a workspace from the artifact contract with required files, registry, and managed Markdown blocks. |
| `workspace_contract/` | Own canonical workspace artifact, scaffold, managed-block, and worker-output path facts consumed by setup and validators. |
| `worker_role_catalog/` | Own canonical worker role facts: prompt templates, delivery folders, mode applicability, method-card expectations, source-trace requirements, required output markers, dispatch aliases, and forbidden worker output classes. |
| `frontier_lifecycle.py` | Pure lifecycle state machine, loop binding, review due checks, portfolio limits, and Markdown rendering. |
| `frontier_review.py` | Main-thread CLI for lifecycle mutations and managed review log updates. |
| `loop_enforcer.py` | Validate evidence ledger loop headers against stable frontier IDs. |
| `gate_check.py` | Enforce stage transition gates, including lifecycle convergence before Stage 3. |
| `scorecard_validator.py` / `timeliness_checker.py` / `synthesis_checker.py` | Validate stage artifacts and freshness requirements. |
| `validate_dossier.py` / `redteam_debate_validator.py` | Validate final report and red-team artifacts. |
| `capability_check.py` | Detect optional search and financial-data capabilities without silently installing them; renders provider names and recommendations from `capability_policy/`. |
| `capability_policy/` | Own canonical capability facts: search chain order, provider ids and labels, finance recommendations, search-record status vocabulary, stage-0 binding, dead-end categories, and missing-tool confidence language. |
| `search_intel.py` | Render advisory prior-query digests and search yield statistics from `search_log.jsonl`; negative trace only, no readiness role. |
| `generate_ultra_packet.py` | Convert Sector Hunt outputs into bounded Ticker Dive packets. |

The main analyst thread may decide whether a frontier should continue or retire. The scripts decide whether that decision is legal, persisted, and gate-compatible.

### Compliance Contract

`scripts/sofa_contract/` is the deterministic authority for workspace completion checks shared by gate checks, dossier validation, report readiness, search logging, dispatch logging, and worker-output compliance. Existing CLI entry points keep their names, but same-purpose rules call this module instead of carrying duplicate rule tables. Markdown workflow files remain human-readable mirrors; machine-readable JSON and JSONL files are the authority where the contract defines one.

`scripts/workspace_contract/` is the deterministic source for workspace shape facts. It does not decide readiness; it gives setup and validation callers one place to ask which files, folders, ledgers, managed blocks, and worker-output paths belong to a SOFA workspace.

## Agent And Subagent Boundary

The main analyst thread owns orchestration and lifecycle mutation. Worker agents receive bounded packets and write product Markdown. They do not hand-edit `frontier_registry.json`, skip gates, or decide final action-class conclusions.

This boundary keeps the research auditable:

- worker products are evidence inputs;
- lifecycle decisions are centralized through `frontier_review.py`;
- stage transitions are checked by `gate_check.py`;
- final reports must pass validation before being treated as usable output.

## Host Adapters

Adapters map SOFA concepts to each host environment: main thread, worker dispatch, planning surface, search/fetch capability, file editing, and shell verification. The adapter layer may name host-specific tools. The core workflow and scripts should not.

See:

- [Codex adapter](adapters/codex.md)
- [Claude Code adapter](adapters/claude-code.md)
- [Generic agent adapter](adapters/generic-agent.md)
- [Qoder-compatible adapter](adapters/qoder-work.md)
- [ZCode adapter](adapters/zcode.md)

## Extension Points

Use these seams when extending SOFA:

| Extension | Preferred landing zone |
|-----------|------------------------|
| New host runtime | Add an adapter under `docs/adapters/`; do not fork the core workflow. |
| New research mode | Add a mode guide and tests before adding scripts. Keep Sector Hunt's no-action-class boundary intact. |
| New deterministic rule | Put it in a script and add focused tests. Do not bury hard rules in prose only. |
| New workspace artifact or scaffold fact | Update `scripts/workspace_contract/` and `tests/test_workspace_contract.py`, then update setup or validator consumers. |
| New worker role or changed worker boundary | Update `scripts/worker_role_catalog/` and `tests/test_worker_role_catalog.py`, then update prompt/docs summaries only as needed. |
| New worker method | Add a private method card and prompt; keep it callable only through the main workflow. |
| New optional capability | Add facts to `scripts/capability_policy/` and detection to `capability_check.py`. Do not silently install tools or write credentials. |

For file-level navigation, see [Codemap](codemap.md).
