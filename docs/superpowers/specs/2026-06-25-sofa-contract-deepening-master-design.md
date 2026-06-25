# SOFA Contract Deepening Master Design

Date: 2026-06-25

Status: master design for future phase specs

## Purpose

SOFA is a host-neutral research harness inspired by Serenity-style OSINT and intelligence-cycle discipline. Its core value is not ordinary repo tidiness. Its core value is preserving a rigorous agent loop:

- evidence-first research;
- Ticker Dive and Sector Hunt mode separation;
- bounded worker dispatch;
- durable ledgers;
- deterministic gates;
- financial bridge before action-class language;
- formal red-team before conviction;
- clear invalidation and watch protocol.

The next architecture work should deepen three shallow areas without changing those research semantics. This master design defines the three-phase direction. It is not an implementation plan and does not authorize code changes by itself. Each phase gets a separate phase spec, implementation plan, branch, and pull request.

## Master Decision

The work will land as three independent phases:

1. Workspace contract module
2. Worker dispatch contract module
3. Capability policy module

Each phase should produce one focused pull request. A later thread may split a phase further if its phase spec proves too large, but phases should not be bundled together.

## Cross-Phase Invariants

These rules are load-bearing. A phase spec may refine them, but it must not weaken them without explicit human approval.

| Invariant | Rule |
| --- | --- |
| Research semantics stay fixed | No phase may loosen Ticker Dive, Sector Hunt, Sector-to-Ultra, action-class, financial bridge, red-team, or evidence-ledger requirements. |
| Main-thread orchestration stays central | Contract modules may make rules inspectable and testable, but they must not make worker agents own lifecycle mutation, final synthesis, or verdicts. |
| Deterministic rules stay deterministic | Path checks, artifact checks, role metadata checks, capability detection, and validation rules belong in deterministic code and tests. |
| Host-neutral core stays host-neutral | Codex, Claude Code, and other host-specific behavior remains in adapters or optional setup docs. Core contracts must not hard-code one host runtime. |
| Existing CLI behavior is preserved first | Early phases should keep current command names, exit codes, and user-visible success/failure meaning unless a phase spec explicitly calls out a change. |
| No broad prompt generation first | Prompt generation is out of scope for the first pass. The first goal is inspectable metadata and validation, not creating a second prompt authoring system. |
| Tests define completion | A phase is not complete unless it adds or updates focused tests for the contract and keeps existing tests passing. |

## Phase 1: Workspace Contract Module

### Goal

Create a deep module that owns the workspace artifact contract behind a small interface. The current workspace facts are spread across `init_workspace.py`, `gate_check.py`, `validate_dossier.py`, tests, and docs. This phase should concentrate path names, required folders, mode-specific artifacts, managed Markdown block names, and required section markers in one implementation.

### Intended Seam

The seam is between scripts that operate on a SOFA workspace and the workspace artifact contract they need to know. Setup, gate, dossier validation, and tests should ask the contract module what the workspace requires instead of carrying their own copies.

### Initial Interface Shape

The first pass should prefer a Python module using only the standard library. It should expose simple read-only facts and helpers, not a large framework.

Expected interface responsibilities:

- list common required files;
- list common required folders;
- list mode-specific required artifacts;
- list managed Markdown block names;
- list required workflow section markers by stage and mode;
- provide path construction helpers for known workspace artifacts;
- optionally expose a lightweight workspace snapshot helper if the phase spec keeps it small.

### Non-Goals

- Do not rewrite the full workspace initializer.
- Do not redesign `state.json` or `frontier_registry.json`.
- Do not change research stage semantics.
- Do not merge the gate validation module into this phase unless the phase spec proves a small shared helper is necessary.

### Completion Gate

The phase is complete when:

- the workspace artifact contract has one source of truth;
- at least `init_workspace.py` and one validation caller use it, or the phase spec explains a smaller first slice;
- focused tests prove ticker and sector workspace requirements;
- existing workspace initialization behavior is preserved;
- docs mention the contract only where useful, without duplicating every detail.

## Phase 2: Worker Dispatch Contract Module

### Goal

Create a deep module that owns worker role metadata and dispatch expectations. Current role facts are repeated across `SKILL.md`, `subagent-dispatch.md`, mode guides, prompt templates, method-card docs, and validation checks.

### Intended Seam

The seam is between the main-thread dispatch assembly and the worker role contract. The main thread should not need to mentally reconstruct prompt paths, method-card expectations, delivery folders, forbidden inputs, and required output fields from multiple prose files.

### Initial Interface Shape

The first pass should define a deterministic worker role catalog. It should be inspectable by tests and usable by validators. It should not generate complete prompts.

Expected interface responsibilities:

- define role slug and display label;
- define prompt template path;
- define mode applicability;
- define delivery folder;
- define required or allowed method cards;
- define forbidden input classes, such as thesis or valuation data for Scout and Sector Mapper;
- define required output markers, such as Method cards loaded;
- provide validation helpers for prompt existence and catalog consistency.

### Non-Goals

- Do not generate full worker prompts.
- Do not change the existing host subagent dispatch process.
- Do not create native Codex or Claude Code agents in this phase.
- Do not make workers own frontier lifecycle, final synthesis, or verdicts.

### Completion Gate

The phase is complete when:

- all existing SOFA worker roles appear in one catalog;
- tests verify prompt paths, delivery folders, method-card references, and required output markers;
- existing prose references either point to the catalog concept or are updated to avoid contradictory role tables;
- existing dispatch semantics remain unchanged.

## Phase 3: Capability Policy Module

### Goal

Create a deep module that owns search and financial capability policy. Current capability order and missing-tool behavior are described in `search-strategy.md`, `capability_check.py`, setup docs, prompts, and initializer output.

### Intended Seam

The seam is between SOFA research workflow and host/environment capability detection. Worker prompts and docs should not carry independent copies of tool order and confidence rules.

### Initial Interface Shape

The first pass should keep the existing capability order unchanged and make it inspectable in code.

Expected interface responsibilities:

- define the general search chain: AnySearch, Exa, Tavily, host-agent built-ins;
- define Chinese financial recommendation: Wind capability;
- define English/global public-market recommendation: yfinance;
- define missing-tool confidence language;
- define safe recommendation text without writing credentials or installing tools;
- support `capability_check.py` rendering from the policy rather than hard-coded repeated strings.

### Non-Goals

- Do not add a new search provider.
- Do not silently install tools or write credentials.
- Do not change SOFA's fallback confidence semantics.
- Do not make yfinance authoritative over filings, exchange releases, or company disclosures.

### Completion Gate

The phase is complete when:

- capability ordering and recommendation text have one deterministic source;
- `capability_check.py` uses the policy module;
- tests assert search chain order, Wind recommendation, yfinance recommendation, and missing-tool behavior;
- docs and prompts no longer need to duplicate long tool-order prose beyond short references or rendered snippets.

## Phase Handoff Rules

Each phase thread must start from this master spec and create its own phase spec before writing code. The phase spec should answer:

| Question | Required answer |
| --- | --- |
| What is the phase goal? | One module and one main seam. |
| What files are owned? | A tight file list, with unrelated files excluded. |
| What is out of scope? | Explicit non-goals copied or refined from this master spec. |
| What existing behavior must stay unchanged? | CLI behavior, docs semantics, agent loop rules, and current tests. |
| What tests come first? | Focused tests that fail before implementation when practical. |
| What is the verification path? | Targeted tests first, then full SOFA baseline checks. |
| What is the PR shape? | One branch, one PR, human review before merge. |

## Recommended Branch And PR Discipline

Each phase should use a separate branch from `SOFA/main`:

- Phase 1: `refactor/workspace-contract`
- Phase 2: `refactor/worker-dispatch-contract`
- Phase 3: `refactor/capability-policy`

Each phase PR should include:

- the phase spec;
- implementation changes;
- focused tests;
- any necessary doc updates;
- verification output in the PR description.

Do not merge a phase PR merely because code compiles. The PR must show that SOFA's research semantics and agent loop remain intact.

## Verification Baseline

Every phase should run the narrowest relevant tests first, then the baseline:

```bash
python -B -m compileall -q scripts tests
python -B -m unittest discover -s tests -p "test_*.py"
```

On this Mac workspace, `python3` may be the available interpreter. Use the current host's working interpreter while preserving cross-platform command guidance in docs.

Documentation-only master spec changes do not require running the full suite as a correctness proof, but phase implementation PRs do.

## Design Review Checklist

Before a phase moves from spec to implementation, verify:

- The phase does not weaken evidence-first research.
- The phase does not compress or bypass Stage 0, Stage 1, Stage 2 loops, financial bridge, or red-team.
- The phase does not move final synthesis or verdict ownership away from the main thread.
- The phase uses module/interface/seam/adapter/locality/leverage language consistently.
- The phase creates one deeper module instead of adding another shallow pass-through.
- The phase can be reviewed by a future agent without reading this full conversation.

## Current Approval State

The human approved the default decisions:

- one phase per PR;
- Workspace contract first;
- Python module shape for the first contract;
- shallow first pass before broad migration;
- no prompt generation initially;
- no capability order changes initially;
- preserve CLI compatibility first;
- place specs under `SOFA/docs/superpowers/specs/`;
- require tests, docs sync, and no behavior weakening as completion gates.

This master spec records that agreement for future phase threads.
