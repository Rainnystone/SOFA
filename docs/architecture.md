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
| `frontier_registry.json` | Registry schema v3 authority for workspace-defined layer labels, nullable frontier layer facts, optional structural parents, discovery provenance, lifecycle status/history, review decisions, and limits. |
| `research_workflow.md` | Human-readable stage and decision log with managed Frontier Review / Discovery blocks plus the deterministic `frontier-layer-coverage` narration. The managed coverage block is never a second authority. |
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

`scripts/dispatch_assembly/` composes dispatches from those facts. Curated prompt templates remain the only prose authority; the assembler fills declared slots, computes delivery paths, screens inputs with pattern tripwires, and attaches negative-trace digests. The main thread keeps packet authorship and dispatch itself.

## Frontier Lifecycle Architecture

Frontiers are first-class research objects. Stage 0 defines the workspace's six structural labels, Stage 1 registers the initial set, and Stage 2 can add, bind, rebind, start, continue, retire, reprioritize, and reactivate them through the lifecycle CLI. `set-layers` is also the explicit v2 adoption path; it does not infer layer placement from existing frontier names or history.

```text
evidence_ledger.md
  -> derive loop counts from stable F{id} headers
  -> check whether Active frontiers crossed an unrecorded review boundary
  -> record Continued or Retired decisions
  -> update frontier_registry.json
  -> render managed review/discovery logs and frontier-layer-coverage narration
  -> gate_check.py blocks Stage 3 until no Active or New frontier remains
```

The review trigger is boundary-window based: a frontier is review-due when `derived_loop_count // every_loops > review_count` and `review_count < max_reviews`. Counts 3, 6, and 9 open review windows; if the main thread overshoots to loop 4 or 5 without recording the review, the frontier remains due until the review is recorded.

`frontier_lifecycle.py` owns registry validation, explicit v2 adoption, layer binding, lifecycle behavior, frontier layer coverage and advisory derivation, and deterministic rendering. `frontier_review.py` owns CLI parsing, mutation orchestration, and the shared render-before-write/two-file persistence path for `frontier_registry.json` and `research_workflow.md`.

Layer gaps are advisory warnings, because they report presence/status rather than research adequacy. A malformed registry or ledger authority is blocking. Gate and loop paths use the canonical registry/ledger document readers; during the Stage 2 transition, `gate_check.py` loads one registry/ledger snapshot and reuses it for coverage warnings, loop binding, lifecycle convergence, and timeliness. `timeliness_checker.py` can consume that preloaded ledger while retaining its standalone read-and-check behavior.

## Deterministic Boundary

Scripts enforce rules that should not depend on agent memory:

| Script | Deterministic responsibility |
|--------|------------------------------|
| `init_workspace.py` | Create a workspace from the artifact contract with required files, registry, and managed Markdown blocks. |
| `workspace_contract/` | Own canonical workspace artifact, scaffold, managed-block, and worker-output path facts consumed by setup and validators. |
| `worker_role_catalog/` | Own canonical worker role facts: prompt templates, delivery folders, mode applicability, method-card expectations, source-trace requirements, required output markers, dispatch aliases, and forbidden worker output classes. |
| `frontier_lifecycle.py` | Validate v2/v3 registries; own explicit v2 adoption, pure lifecycle and layer binding, loop/review rules, portfolio limits, coverage and advisory derivation, and Markdown rendering. |
| `frontier_review.py` | Parse main-thread lifecycle commands, orchestrate mutations, render before writes, and persist registry/workflow changes through the shared two-file transaction path. |
| `loop_enforcer.py` | Validate stable-ID ledger headers from supplied registry/ledger documents, with a standalone reader retained for direct use. |
| `gate_check.py` | Enforce stage transitions; at Stage 2, reuse one registry/ledger snapshot for advisory coverage, loop binding, lifecycle convergence, and freshness checks. Malformed authority blocks while layer gaps warn. |
| `timeliness_checker.py` | Validate freshness from the gate's preloaded ledger or, when run standalone, read the ledger itself. |
| `scorecard_validator.py` / `synthesis_checker.py` | Validate scorecards and synthesis artifacts. |
| `validate_dossier.py` / `redteam_debate_validator.py` | Validate final report and red-team artifacts. |
| `capability_check.py` | Detect optional search and financial-data capabilities without silently installing them; renders provider names and recommendations from `capability_policy/`. |
| `capability_policy/` | Own canonical capability facts: search chain order, provider ids and labels, finance recommendations, search-record status vocabulary, stage-0 binding, dead-end categories, and missing-tool confidence language. |
| `search_intel.py` | Render advisory prior-query digests and search yield statistics from `search_log.jsonl`; negative trace only, no readiness role. |
| `dispatch_assembly/` + `assemble_dispatch.py` | Assemble worker dispatch text deterministically from catalog slot facts, curated prompt templates, and machine-trace attachments. Read-only: no workspace writes, no dispatch-log writes, no dispatching, no readiness role. |
| `framing_contract/` + `framing_intake.py` | Own the Stage 0 framing intent contract: schema, field vocabulary, completeness evaluation, JSON authority, Markdown mirror, and mutation CLI. Consumed by `sofa_contract` for the stage_0 gate; never enters worker dispatches. |
| `source_cache/` + `archive_source.py` | Own the workspace source cache: append-only excerpt archive (`sources/` + `sources_index.jsonl`), hash dedupe, index validation, and the identifiers-only bibliography renderer. Mutation is main-thread-only through the CLI; workers surface candidates in deliveries. |
| `generate_ultra_packet.py` | Convert Sector Hunt outputs into bounded Ticker Dive packets. |

The main analyst thread may decide whether a frontier should continue or retire. The scripts decide whether that decision is legal, persisted, and gate-compatible.

### Framing Intent Contract

`scripts/framing_contract/` owns the structured Stage 0 framing intent facts as a `framing_contract.json` workspace authority artifact plus a managed Markdown mirror in `research_workflow.md` (the `frontier_registry.json` authority-and-mirror pattern). The module owns the research-posture vocabulary (`fresh`, `verify-narrative`, `revisit`, `compare`) that future revisit work consumes. `sofa_contract` consumes its completeness facts for the stage_0 readiness gate; the module itself never decides advancement. All mutations go through `scripts/framing_intake.py`, which re-renders the mirror in the same operation. The framing contract is main-thread intent; it never enters worker dispatches, packets, or prompts (intent is thesis-adjacent context that worker isolation rules exclude). Extension seam: a new framing field adds a fact in `framing_contract/` plus a focused test; no consumer outside the contract, CLI, and stage_0 gate needs to change.

### Workspace Source Cache

`scripts/source_cache/` owns the deep-read-once-reuse-everywhere seam: `sources_index.jsonl` is the machine authority (source id, URL, title, retrieval date, grade, excerpt path, content hash) and `sources/` holds bounded key excerpts. All mutation goes through `scripts/archive_source.py` (append-only, hash-deduplicating); workers never write the cache — they surface `Source Archive Candidates` in deliveries and the main thread archives after acceptance. `sofa_contract` validates a present index at every gate and accepts registered source-id citations from the current workspace's valid index as worker source traces; `dispatch_assembly` attaches the screened identifiers-only bibliography. The cache is research support: grades are recorded but never computed with, and cached excerpts never become authoritative over live filings. Extension seam: a new index field adds a fact in `source_cache/` plus a focused test.

### Compliance Contract

`scripts/sofa_contract/` is the deterministic authority for workspace completion checks shared by gate checks, dossier validation, report readiness, search logging, dispatch logging, and worker-output compliance. Existing CLI entry points keep their names, but same-purpose rules call this module instead of carrying duplicate rule tables. Markdown workflow files remain human-readable mirrors; machine-readable JSON and JSONL files are the authority where the contract defines one.

`scripts/workspace_contract/` is the deterministic source for workspace shape facts. It does not decide readiness; it gives setup and validation callers one place to ask which files, folders, ledgers, managed blocks, and worker-output paths belong to a SOFA workspace.

## Revisit Contract

The revisit contract is a Ticker-only append-only domain. `scripts/revisit_cycle.py` is its main-thread CLI; Sector Hunt, ordinary dispatch, action-class meanings, and existing research floors remain outside this surface. Its allowed dependency direction is:

```text
revisit_cycle.py -> revisit_contract
revisit_cycle.py -> sofa_contract.revisit_readiness
dispatch_assembly -> revisit_contract.context
sofa_contract -> revisit_contract
```

The acyclic rule is explicit: **revisit_contract must not import sofa_contract**. `revisit_contract` owns cycle schema, validation, rendering, transitions, and persistence; `sofa_contract` remains the sole pass/fail verdict owner. The top-level CLI composes the two without moving verdict authority into the mutation domain.

Authority is split by purpose, not duplicated:

- **pointer authority**: `revisit_contract.json` names the exact canonical current Markdown path/hash and revision lineage;
- **cycle authority**: `revisit_cycles/RC-####.json` owns immutable intake, trigger/claim/frontier facts, status, candidate, and audit; its Markdown mirror is deterministic human-readable narration, not a second authority;
- report bytes become an immutable registered candidate before publication, while search, dispatch, source, framing, and frontier facts remain with their existing owners.

Cycle commits use **mirror-first** and **JSON-last** persistence. Publication is report-first, then immutable-cycle-next (completed mirror first and completed cycle JSON last), and **pointer-last**. A pointer replacement failure therefore leaves the old current selection authoritative and exposes a completed-unpublished pointer-only retry instead of rewriting the completed cycle.

`revisit_contract.context` is the role-safe context boundary for revisit Scout and Challenge packets: it selects only target-bound neutral facts, negative trace, and explicit source references, while the main thread keeps intake, acceptance, synthesis, lifecycle, and publication authority. Formal Red Team retains the complete current-thesis floor.

The Phase 9 seam is limited to **stable typed facts** and immutable completed lineage. Phase 8 deliberately provides **no snapshot/compiler prebuild**: no persisted workspace snapshot, context compiler, migration layer, or general context manifest is introduced.

### Revisit Readiness And Observed-Read Consistency

`scripts/sofa_contract/revisit_readiness.py` is the only revisit pre-report readiness seam. Direct (`evaluate_revisit_readiness(workspace, cycle_id)`), profile (`ContractProfile(target="revisit_report")`), and the real `check` command (`check_revisit_readiness`) share one global cycle history, one ordered thirteen-row semantic requirement plan, and one observed-read generation closure. No caller constructs an authority path list, a requested-source generation subset, or a manual authority union; the old CLI-side capture and the separate discovered-cycle semantic plan were deleted in favor of the single seam. `sofa_contract` remains the only readiness verdict authority; `revisit_readiness` composes existing domain owners (registry, framing, source cache, frontier floor, search, dispatch, worker-output) over preloaded bytes and returns strict facts plus a `ContractResult`, never a second verdict.

`scripts/revisit_contract/generation.py` observes only the files, absences, resolved targets, and directory memberships that semantic owners actually consume during one evaluation. It caches the first observation per lexical path and captures direct membership once per lexical directory; recursive listings are composed from those cached direct snapshots, so no recursion mode creates a second generation. A lexical authority read by multiple requirements is physically read once; freezing the session yields an immutable `GenerationClosure` whose `require_unchanged()` recheck detects byte drift, disappearance, same-byte target retarget, absence-to-appearance, and directory-member add/remove/rename/type-change. It is short-lived and in-memory only; it is neither a whole-workspace snapshot nor a Phase 9 context compiler or migration layer.

`scripts/revisit_contract/store.py` remains the transition, render, persistence, and rollback owner. When `persist_cycle` is given a `generation_closure`, it derives the only allowed mutation paths (`revisit_cycles/RC-NNNN.json` and its Markdown mirror) from the named cycle id, rechecks the unexcluded closure before and after the write through the package-private `_require_unchanged_except`, and restores exact prior bytes on a handled post-write drift. The consistency model is optimistic generation verification (a single boundary recheck plus a write-window recheck), not database-level multi-file atomicity; the workspace transaction remains re-entrant for cooperating writers but generation-closure rechecks are mandatory even while the lock is held. Any `LifecycleError` from canonical `frontier_lifecycle.validate_registry` maps to `REVISIT_FRONTIER_REGISTRY_MALFORMED`; any `AuthorityDriftError` from the closure maps to `REVISIT_AUTHORITY_DRIFT` at the exact lexical path. Malformed nested registry members can no longer be masked by a valid sibling, and a valid-but-unreferenced indexed excerpt that drifts after semantic use can no longer escape the consumed-generation closure.

A `check` returns one of three effects: `BLOCKED` (semantic or drift failure, zero writes), `TRANSITIONED` (one `active -> ready_for_report` transition with exactly one audit at the supplied timestamp, only the cycle JSON and mirror change), or `UNCHANGED_READY` (a byte-preserving no-op with no audit). No new external search tool, provider, MCP, skill, or required capability was introduced; the efficiency gain is reduced validator I/O and orchestration duplication, not a change to search-provider policy.

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
| New dispatch slot, filename convention, or input tripwire | Update `scripts/worker_role_catalog/` facts and `tests/test_worker_role_catalog.py`; the assembler consumes the catalog and needs no per-role code. |

For file-level navigation, see [Codemap](codemap.md).
