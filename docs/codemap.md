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
| `scripts/init_workspace.py` | `tests/test_workspace_scripts.py` | Create workspace files, registry, managed Markdown blocks, and initial state from `workspace_contract` facts. |
| `scripts/workspace_contract/` | `tests/test_workspace_contract.py`, `tests/test_workspace_scripts.py`, `tests/test_sofa_contract.py` | Canonical workspace artifact/scaffold facts, mode-specific scaffold paths, managed blocks, and worker-output path classification. |
| `scripts/worker_role_catalog/` | `tests/test_worker_role_catalog.py`, `tests/test_sofa_contract.py` | Canonical worker role facts, prompt paths, delivery folders, method-card expectations, source-trace rules, forbidden worker-output classes, and dispatch aliases consumed by `sofa_contract`. |
| `scripts/capability_policy/` | `tests/test_capability_policy.py`, `tests/test_capability_check.py`, `tests/test_sofa_contract.py` | Canonical capability facts: search chain, provider ids, finance recommendations, search-record vocabulary, and render helpers consumed by `capability_check.py`, `init_workspace.py`, and `sofa_contract`. |
| `scripts/search_intel.py` | `tests/test_search_intel.py`, `tests/test_cli_utf8_stdout.py` | CLI rendering prior-query digests and advisory yield statistics from `capability_policy.search_records`. |
| `scripts/sofa_contract/` | `tests/test_sofa_contract.py` | Shared compliance contract package for structured pass/fail/warn results and DSV4P-hardening checks; consumes `workspace_contract` for workspace shape facts and `worker_role_catalog` for role-specific dispatch and worker-output checks. |
| `scripts/frontier_lifecycle.py` | `tests/test_frontier_lifecycle.py` | Pure lifecycle model: stable ID loop binding, transition legality, review due, portfolio limits, and rendering. |
| `scripts/frontier_review.py` | `tests/test_frontier_review_cli.py` | CLI for adding, starting, reviewing, retiring, reactivating, and reporting frontier status. |
| `scripts/loop_enforcer.py` | `tests/test_frontier_lifecycle.py` | Validate ledger loop headers against registry IDs. |
| `scripts/gate_check.py` | `tests/test_frontier_gate.py` | Enforce stage transition gates, including lifecycle convergence before Stage 3. |
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
2. Update `scripts/worker_role_catalog/`.
3. Update `scripts/sofa_contract/` only when readiness or worker-output checks consume the changed fact.
4. Keep role tables in `skills/sofa-analyze/SKILL.md` and `skills/sofa-analyze/references/subagent-dispatch.md` as short human-readable summaries.
5. Run `python -B -m unittest tests.test_worker_role_catalog tests.test_sofa_contract`.
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

1. Add or update focused tests in `tests/test_frontier_lifecycle.py` for pure behavior.
2. Add or update CLI tests in `tests/test_frontier_review_cli.py` when command behavior or persistence changes.
3. Modify `scripts/frontier_lifecycle.py` first for shared legality and rendering.
4. Modify `scripts/frontier_review.py` only for CLI parsing, transaction behavior, and workspace I/O.
5. If stage convergence changes, update `scripts/gate_check.py` and `tests/test_frontier_gate.py`.
6. Update `workflow-guide.md`, `ticker-dive-guide.md`, and `sector-hunt-guide.md` if user-facing workflow semantics changed.
7. Run targeted lifecycle tests, then the full suite.

Current lifecycle source of truth:

- per-frontier loop counts are derived from `evidence_ledger.md` headers;
- `frontier_registry.json` stores status, source, lifecycle history, review decisions, and portfolio limits;
- `research_workflow.md` receives managed review and discovery logs rendered from registry data;
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
