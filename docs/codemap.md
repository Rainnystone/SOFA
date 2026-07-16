# Codemap

This codemap is for maintainers and coding agents working inside the SOFA repo. Use it to find the right file before editing, keep docs and tests aligned, and avoid broad refactors.

## Top-Level Map

| Path | Purpose |
|------|---------|
| `README.md` / `README_CN.md` | Public product entrypoints. Keep them readable and short. Link deeper details instead of expanding them inline. |
| `skills/sofa-analyze/SKILL.md` | The entry router for host agents. It should stay lean and route to references. |
| `skills/sofa-analyze/references/` | Workflow guides, search strategy, report templates, method-card specification, and reusable knowledge. |
| `skills/sofa-analyze/method-cards/` | Private worker methods. These are not user-invocable skills. |
| `scripts/` | Deterministic Python and shell tools for setup, gates, lifecycle, validators, and packet generation. |
| `scripts/prompts/` | Worker prompt templates used by the main workflow. |
| `docs/` | Installation, capability setup, architecture, codemap, report guide, and host adapters. |
| `tests/` | Unit and structure tests that keep the repo shape and deterministic rules stable. |
| `assets/` | README images and other repo-level media. |

## Workflow And Skill Surfaces

| File | Edit when |
|------|-----------|
| `skills/sofa-analyze/SKILL.md` | The entry routing, start instructions, or high-level mode selection changes. |
| `skills/sofa-analyze/references/workflow-guide.md` | Shared stage sequence, lifecycle rules, loop rhythm, or global gate language changes. |
| `skills/sofa-analyze/references/ticker-dive-guide.md` | Ticker-specific evidence frontier loop, thesis path, red-team path, or final decision boundary changes. |
| `skills/sofa-analyze/references/sector-hunt-guide.md` | Sector-specific mapping loop, chokepoint scoring, ranked queue, or no-action-class boundary changes. |
| `skills/sofa-analyze/references/sector-to-ultra-guide.md` | Sector Hunt output needs to become Ticker Dive / Ultra Dive packets. |
| `skills/sofa-analyze/references/search-strategy.md` | Operational search policy, evidence source handling, or source freshness rules change; capability order, provider ids, and recommendation facts belong to `scripts/capability_policy/`. |
| `skills/sofa-analyze/references/final-report.md` | Final report structure, action-class language, or evidence appendix expectations change. |
| `skills/sofa-analyze/references/method-card-spec.md` | Private method card format or visibility rules change. |

Keep shared lifecycle language synchronized across `workflow-guide.md`, `ticker-dive-guide.md`, `sector-hunt-guide.md`, and the lifecycle scripts.

## Deterministic Script Map

| Script | Main tests | Responsibility |
|--------|------------|----------------|
| `scripts/init_workspace.py` | `tests/test_workspace_scripts.py` | Create workspace files, the schema-v3 registry, initial state, and deterministic managed blocks (including `frontier-layer-coverage`) from `workspace_contract` facts. |
| `scripts/workspace_contract/` | `tests/test_workspace_contract.py`, `tests/test_workspace_scripts.py`, `tests/test_sofa_contract.py` | Canonical workspace artifact/scaffold facts, mode-specific paths, managed-block registration/replacement helpers, and worker-output path classification. The layer block is a rendering surface, not another JSON authority. |
| `scripts/worker_role_catalog/` | `tests/test_worker_role_catalog.py`, `tests/test_sofa_contract.py` | Canonical worker role facts, prompt paths, delivery folders, method-card expectations, source-trace rules, forbidden worker-output classes, and dispatch aliases consumed by `sofa_contract`. |
| `scripts/capability_policy/` | `tests/test_capability_policy.py`, `tests/test_capability_check.py`, `tests/test_sofa_contract.py` | Canonical capability facts: search chain, provider ids, finance recommendations, search-record vocabulary, and render helpers consumed by `capability_check.py`, `init_workspace.py`, and `sofa_contract`. |
| `scripts/search_intel.py` | `tests/test_search_intel.py`, `tests/test_cli_utf8_stdout.py` | CLI rendering prior-query digests and advisory yield statistics from `capability_policy.search_records`. |
| `scripts/dispatch_assembly/` + `scripts/assemble_dispatch.py` | `tests/test_dispatch_assembly.py`, `tests/test_worker_role_catalog.py`, `tests/test_cli_utf8_stdout.py` | Deterministic dispatch composition from worker-role slot facts, filename templates, input tripwires, and prior-query digest attachment. |
| `scripts/framing_contract/` + `scripts/framing_intake.py` | `tests/test_framing_contract.py`, `tests/test_cli_utf8_stdout.py` | Stage 0 framing intent contract authority: schema, field vocabulary, completeness evaluation, JSON authority, Markdown mirror, mutation CLI, and research-posture vocabulary. Consumed by `sofa_contract` for the stage_0 gate. |
| `scripts/source_cache/` + `scripts/archive_source.py` | `tests/test_source_cache.py`, `tests/test_cli_utf8_stdout.py` | Workspace source cache authority: index schema, append-only archival, hash dedupe, validation issue codes, source-id pattern, and bibliography rendering. Consumed by `sofa_contract` and `dispatch_assembly`. |
| `scripts/sofa_contract/` | `tests/test_sofa_contract.py` | Shared compliance contract package for structured pass/fail/warn results and DSV4P-hardening checks; consumes `workspace_contract` for workspace shape facts and `worker_role_catalog` for role-specific dispatch and worker-output checks. |
| `scripts/sofa_contract/revisit_readiness.py` | `tests/test_revisit_readiness.py` | Sole thirteen-row revisit readiness composition and atomic `check` orchestration; direct/profile/check share one global history, one ordered semantic plan, and one observed-read generation closure. Exports `evaluate_revisit_readiness`, `check_revisit_readiness`, `RevisitCheckEffect`, `RevisitCheckOutcome`. |
| `scripts/revisit_contract/generation.py` | `tests/test_revisit_generation.py` | Observed-read file/absence/directory generations and immutable closure verification; caches first observation per lexical path and per `(relative_path, recursive)` directory key. Short-lived, in-memory only; consumed by readiness composition and persistence. |
| `scripts/frontier_lifecycle.py` | `tests/test_frontier_lifecycle.py` | Pure registry/lifecycle model: v2/v3 validation, explicit v2 adoption, layer binding, stable-ID loop facts, transitions, review due, portfolio limits, frontier layer coverage and advisories, and rendering. |
| `scripts/frontier_review.py` | `tests/test_frontier_review_cli.py`, `tests/test_cli_utf8_stdout.py` | Parser and mutation orchestrator for lifecycle, `set-layers`, and `bind-layer`; owns shared render-before-write and two-file registry/workflow persistence. |
| `scripts/loop_enforcer.py` | `tests/test_frontier_lifecycle.py`, `tests/test_frontier_gate.py` | Validate ledger loop headers against registry IDs from supplied canonical documents; direct standalone reads remain supported. |
| `scripts/gate_check.py` | `tests/test_frontier_gate.py` | Enforce stage transitions; at Stage 2, read one registry/ledger snapshot for warning-only layer advisories, loop binding, lifecycle convergence, and freshness. Malformed registry/ledger authority blocks. |
| `scripts/timeliness_checker.py` | `tests/test_frontier_gate.py` | Consume the Stage 2 gate's preloaded ledger without a second read while retaining standalone behavior. |
| `scripts/capability_check.py` | `tests/test_capability_check.py` | Detect optional search and financial-data capability availability. |
| `scripts/generate_ultra_packet.py` | structure and workspace tests | Generate bounded Ultra Dive packets from Sector Hunt outputs. |
| `scripts/run_coverage.py` | manual verification gate | Run cross-platform coverage for the lifecycle module. |
| report and score validators | structure and targeted validator tests | Validate scorecards, freshness, synthesis, red-team debate, and final dossiers. |

If a script enforces a rule that appears in a guide, update both the script tests and the guide text in the same change.

## Workspace Artifact Contract Change Path

Use this path when changing workspace files, folders, ledgers, managed blocks, or worker-output path classification:

1. Update focused tests in `tests/test_workspace_contract.py`.
2. Update `scripts/workspace_contract/`.
3. Update setup or validator consumers such as `scripts/init_workspace.py` and `scripts/sofa_contract/`.
4. Run `python -B -m unittest tests.test_workspace_contract tests.test_workspace_scripts tests.test_sofa_contract`.
5. Run the full baseline before committing.

## Worker Role Catalog Change Path

Use this path when changing worker roles, prompt-template paths, delivery folders, method-card expectations, source-trace requirements, required output markers, forbidden worker-output classes, or dispatch aliases:

1. Update focused tests in `tests/test_worker_role_catalog.py`.
2. Update `scripts/worker_role_catalog/` (role facts, dispatch slots, filename templates, input tripwires).
3. Update `scripts/sofa_contract/` only when readiness or worker-output checks consume the changed fact.
4. Keep role tables in `skills/sofa-analyze/SKILL.md` and `skills/sofa-analyze/references/subagent-dispatch.md` as short human-readable summaries.
5. Run `python -B -m unittest tests.test_worker_role_catalog tests.test_sofa_contract tests.test_dispatch_assembly`.
6. Run the full baseline before committing.

## Capability Policy Change Path

Use this path when changing the search chain, provider recommendations, finance capability guidance, or search-record vocabulary:

1. Update focused tests in `tests/test_capability_policy.py`.
2. Update `scripts/capability_policy/`.
3. Update `capability_check.py` detection only when the probe itself changes.
4. Run `python -B -m unittest tests.test_capability_policy tests.test_capability_check tests.test_sofa_contract tests.test_search_intel`.
5. Run the full baseline before committing.

## Frontier Lifecycle Change Path

Use this path for lifecycle changes:

After focused tests pin the intended contract, the safe change order is pure model first, CLI/persistence second, and derived consumers third:

1. Add or update pure-model tests in `tests/test_frontier_lifecycle.py`.
2. Modify `scripts/frontier_lifecycle.py` for registry validation/adoption, shared legality, binding, derivation, and rendering.
3. Add or update `tests/test_frontier_review_cli.py` and modify `scripts/frontier_review.py` for CLI parsing, mutation orchestration, and transaction behavior.
4. Update derived consumers only as required: `workspace_contract`/`init_workspace.py` with `tests/test_workspace_contract.py` and `tests/test_workspace_scripts.py`; gate/loop/timeliness with `tests/test_frontier_gate.py`.
5. Update `workflow-guide.md`, `ticker-dive-guide.md`, and `sector-hunt-guide.md` if user-facing workflow semantics changed.
6. Run targeted lifecycle, CLI, workspace, and gate tests, then the full suite.

Current lifecycle source of truth:

- per-frontier loop counts are derived from `evidence_ledger.md` headers;
- schema-v3 `frontier_registry.json` owns workspace layer labels, nullable bindings, optional structural parents, provenance, status, lifecycle history, review decisions, and portfolio limits;
- `research_workflow.md` receives managed review, discovery, and frontier-layer-coverage narration rendered from registry data; those blocks are not separate authorities;
- no Active or New frontier may remain before Stage 3.

## Documentation Change Path

| Change type | Files to check |
|-------------|----------------|
| Public positioning or quickstart | `README.md`, `README_CN.md`, `docs/installation.md` |
| Architecture or repo navigation | `docs/architecture.md`, `docs/codemap.md`, README deeper-doc links |
| Host mapping | One file under `docs/adapters/`; avoid changing the core workflow unless the mapping reveals a real core gap. |
| Capability facts or recommendations | `scripts/capability_policy/`, `tests/test_capability_policy.py`, `docs/capability-setup.md`; check `scripts/capability_check.py` and `tests/test_capability_check.py` only when detection or probe behavior changes. |
| Report style | `docs/report-guide.md`, `skills/sofa-analyze/references/final-report.md` |

Keep README concise. If a section grows into implementation detail, move it to `docs/` and link it.

## Verification Commands

Use the narrowest useful command while editing, then run the full checks before committing.

> **Interpreter name:** commands use `python`. On Windows use `python` or `py`; on the rare Linux distro that only ships `python3`, use that. The `-B` flag (equivalent to `PYTHONDONTWRITEBYTECODE=1`) avoids writing `.pyc` files and works on every OS without shell-specific env syntax.

```bash
python -B -m unittest tests.test_structure
python -B -m unittest tests.test_frontier_lifecycle
python -B -m unittest tests.test_frontier_review_cli
python -B -m compileall -q scripts tests
python -B -m unittest discover -s tests -p "test_*.py"
git diff --check
```

For lifecycle coverage:

```bash
python scripts/run_coverage.py
```

For revisit readiness and the observed-read generation primitive:

```bash
python -B -m unittest tests.test_revisit_generation
python -B -m unittest tests.test_revisit_readiness
python -B -m unittest tests.test_revisit_contract
```

`run_coverage.py` is cross-platform (Windows, macOS, Linux) and invokes coverage through `sys.executable`. If your environment is an externally managed Python (PEP 668), install `coverage` from `requirements-dev.txt` into a virtual environment first:

```bash
python -m venv .venv-coverage
# Windows: .venv-coverage\Scripts\activate
# macOS/Linux: source .venv-coverage/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/run_coverage.py
```

## Boundaries To Preserve

- Do not put host-specific tool names into core guides or scripts; keep them in adapters.
- Do not let Sector Hunt produce action-class conclusions.
- Do not hand-edit `frontier_registry.json` in workflow instructions; use `frontier_review.py`.
- Do not make optional search or financial-data tools hard dependencies.
- Do not turn private method cards into user-invocable skills.
- Do not replace deterministic validators with prose-only instructions.
