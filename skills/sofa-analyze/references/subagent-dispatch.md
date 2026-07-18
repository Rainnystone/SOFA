# Subagent Dispatch Guide

This file defines host-neutral worker dispatch rules for SOFA. Each host adapter maps these rules to its own subagent mechanism.

## Architecture

The main thread owns orchestration, durable state, cross-loop synthesis, and final decisions. Subagent workers own bounded evidence collection or challenge tasks.

Main-thread responsibilities:

- route the workflow;
- write Frontier Packets, Mapping Packets, and Ultra packets;
- dispatch one bounded worker task at a time when there is a dependency;
- read worker deliverables from disk;
- update `evidence_ledger.md`, `research_workflow.md`, and the host progress tracker;
- run deterministic gates;
- decide Continue, Pivot, Fork, Stop, or Needs Primary Evidence.

Worker responsibilities:

- load only the specified prompt, method cards, packet, and reference paths;
- perform the assigned search, mapping, challenge, financial, or red-team task;
- write the complete output to the assigned file;
- return a concise summary to the main thread.

## Context Isolation

Pass only:

1. role definition;
2. current packet;
3. relevant method-card paths;
4. relevant reference paths;
5. output schema;
6. delivery file path;
7. search and fetch capability guidance from `search-strategy.md`.

Do not pass:

- full conversation history;
- complete evidence ledger;
- current thesis or desired conclusion;
- stock price, market cap, or valuation stance for Scout or Sector Mapper work;
- other worker outputs unless the mode guide explicitly requires them.

## File Delivery

Every worker must write its complete output to the path assigned by the main thread. The file is the durable source; the worker return is only a summary.

Expected workspace folders:

```text
research_workflow.md
evidence_ledger.md
claim_ledger.md
search_log.md
capability_report.md
scouts/
challenges/
maps/
coverage/
financials/
redteam/
reports/
dive_packets/
```

Do not overwrite prior worker files. Use loop, round, or version identifiers in filenames.

### Main-thread-only artifacts

`sources/` and `sources_index.jsonl` are main-thread-only source-cache artifacts, not worker delivery folders. Workers never write these paths. A deep read of a high-value document is surfaced as a `Source Archive Candidates` section in the delivery; the main thread reviews the candidates and archives confirmed excerpts append-only via `python {PLUGIN_DIR}/scripts/archive_source.py "{WORKSPACE}" add ...` after accepting the product.

## Role Reference

This table is a dispatch guide summary. The authoritative worker role facts for prompt paths, delivery folders, method-card expectations, source-trace rules, required output markers, forbidden worker-output classes, and dispatch aliases live in `../../../scripts/worker_role_catalog/`.

| Role | Prompt | Mode | Delivery |
|------|--------|------|----------|
| Frontier Scout | `scripts/prompts/scout_prompt.md` | Ticker | `scouts/` |
| Challenge Probe | `scripts/prompts/challenge_prompt.md` | Ticker | `challenges/` |
| Sector Mapper | `scripts/prompts/sector_mapper_prompt.md` | Sector | `maps/` |
| Coverage Challenge | `scripts/prompts/coverage_challenge_prompt.md` | Sector | `coverage/` |
| Supply Chain Mapper | `scripts/prompts/supply_chain_prompt.md` | Ticker / Sector / Ultra | `maps/` |
| Customer Graph Mapper | `scripts/prompts/customer_graph_prompt.md` | Ticker / Sector / Ultra | `maps/` |
| Financial Bridge Analyst | `scripts/prompts/financial_bridge_prompt.md` | Ticker / Sector / Ultra | `financials/` |
| Red Team | `scripts/prompts/red_team_prompt.md` | Ticker / Sector / Ultra | `redteam/` |

Dispatch slot literals and delivery filename templates are catalog facts in `../../../scripts/worker_role_catalog/`. In the manual fallback, read the standalone prompt file before dispatching; never reconstruct a worker prompt from memory or from this summary.

## Dispatch Assembly

Assemble dispatch text deterministically:

```bash
python {PLUGIN_DIR}/scripts/assemble_dispatch.py --workspace "{WORKSPACE}" --role <role> --packet-file <packet.md> [--loop N] [--frontier-slug slug] [--round N] [--ticker T] [--version N] [--no-digest] [--no-sources]
```

The assembler fills the catalog-declared slots in the curated prompt template, computes the canonical delivery path, screens the packet against role forbidden-input tripwires (pattern-based only — semantic isolation stays the main thread's responsibility), and attaches the prior-query digest and the identifiers-only source bibliography when available (pass --no-digest / --no-sources to bypass explicitly). The main thread still authors the packet, reviews the assembled text, and dispatches through the host subagent mechanism. After dispatch, the main thread records the dispatch_log.jsonl entry; the assembler never writes it.

Name-field values (`--loop`, `--frontier-slug`, `--round`, `--ticker`, `--version`) are ASCII-only (`[A-Za-z0-9_-]`); romanize Chinese frontier names before using them in filenames.

### Ticker revisit Scout/Challenge context

For a revisit Scout or Challenge, append this optional group to the ordinary assembler command:

```text
--revisit-cycle RC-#### --frontier F# --claim RC-####-CL-## [--claim RC-####-DC-##]
```

The three field types are **all-or-none**: one cycle, one frontier, and at least one repeatable claim are required together, and revisit assembly also requires the ordinary `--loop` name field. Every claim must belong to that cycle and be legally bound to the target frontier.

For these two isolated roles, revisit context **replaces the ordinary whole-workspace prior-query digest and source bibliography**. `revisit_contract.context` supplies only the target-filtered negative trace and explicitly referenced source IDs/raw excerpts; the existing forbidden-input screening still covers the packet, selected context, and final attachments. Unrelated frontier facts, interpreted positive trace, thesis, action class, confidence, framing intent, and prior worker conclusions stay out.

**Non-revisit dispatch is unchanged.** Ordinary assembly keeps its existing digest/bibliography behavior and role fields. **Formal Red Team still receives the complete current thesis** and its existing input floor when the decision matrix requires that role; the isolated revisit attachment does not replace Formal Red Team or turn Challenge into Red Team.

Degraded fallback (manual assembly):

1. Read the standalone prompt template.
2. Prepare the current packet, evidence summary, constraints, delivery path, and required references.
3. Add method-card paths and the instruction that the packet overrides method-card generalities.
4. Add the output schema and required file write.
5. Dispatch through the host subagent mechanism.

## Parallelism

Parallel work is allowed only when tasks are independent and write to different files.

| Scenario | Rule |
|----------|------|
| Multiple independent frontiers | May run limited parallel scouts if the host supports it. |
| Scout followed by Challenge Probe | Serial. Challenge depends on Scout output. |
| Financial Bridge and Red Team | Serial. Red Team needs bridge evidence. |
| Sector Mapper followed by Coverage Challenge | Serial. Coverage depends on mapper output. |
| Supply-chain and customer-graph specialists | May run in parallel if packets are independent. |

## Failure Handling

- Empty or timed-out worker output: mark the task blocked and record what is missing.
- Schema mismatch: extract usable evidence, record missing fields, and decide whether to rerun.
- No evidence found: record as `No Evidence Found`; do not treat it as evidence against the claim.
- Missing search or financial capability: record lower confidence and use the next configured fallback.

## Return Verification

After each worker returns, the main thread checks:

- delivery file exists;
- required sections are present;
- sources include URLs or source identifiers;
- evidence grades are assigned;
- search exhaustion and dead ends are recorded;
- method cards loaded are declared;
- worker did not produce forbidden conclusions.

Only after verification should the main thread update ledgers and make the next workflow decision.
