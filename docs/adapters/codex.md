# Codex Adapter

## Mapping

| SOFA concept | Codex mapping |
|--------------|---------------|
| Main thread | Current Codex conversation |
| Host progress tracker | `update_plan` when available, plus project planning files |
| Host subagent mechanism | Codex subagent or worker thread when the main thread dispatches one |
| File editing | `apply_patch` for manual edits |
| Search/fetch | Available web tools or configured external capabilities |
| Verification | Terminal commands through the shell tool |

## Start Examples

Ticker Dive:

```text
Use SOFA Analyze on NVDA supplier X as a Ticker Dive. Initialize a workspace, run framing, and stop after Stage 1 for direction selection.
```

Sector Hunt:

```text
Use SOFA Analyze for CPO laser supply-chain bottlenecks as a Sector Hunt. Produce the dependency ladder, chokepoint matrix, and ranked queue.
```

Sector-to-Ultra:

```text
Convert the top two Sector Hunt queue items into Ultra packets under dive_packets, then ask which candidate to deep dive.
```
