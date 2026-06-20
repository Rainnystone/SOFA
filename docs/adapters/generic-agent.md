# Generic Agent Adapter

## Mapping

| SOFA concept | Generic mapping |
|--------------|-----------------|
| Main thread | The current agent conversation or controller process |
| Host progress tracker | Any explicit plan, checklist, issue tracker, or project planning file |
| Host subagent mechanism | Any isolated worker mechanism that can receive a bounded packet and write a file |
| Search/fetch | Any configured search API, browser tool, fetch tool, or manual source collection process |
| File editing | The host's normal file-edit mechanism |
| Verification | Local shell, CI, or deterministic validation scripts |

## Start Examples

Ticker Dive:

```text
Start SOFA Analyze in ticker mode for the named company, initialize the workspace, run Stage 0, and present the provisional frontiers.
```

Sector Hunt:

```text
Start SOFA Analyze in sector mode for the named technology theme, produce a dependency ladder, and keep the final output as a ranked queue.
```

Sector-to-Ultra:

```text
Use the completed Sector Hunt ranked queue to generate Ultra packets in dive_packets, then run a full company-level dive on the selected packet.
```
