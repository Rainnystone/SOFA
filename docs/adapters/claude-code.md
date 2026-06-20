# Claude Code Adapter

## Mapping

| SOFA concept | Claude Code mapping |
|--------------|---------------------|
| Main thread | Current Claude Code session |
| Host progress tracker | Host todo tracker plus project planning files |
| Host subagent mechanism | Host task dispatch tool |
| User clarification | Host clarification UI when available, otherwise ask directly |
| Search/fetch | Host web search and fetch tools, or configured external capabilities |
| File editing | Edit/Write for files, shell for verification |

## Start Examples

Ticker Dive:

```text
Use SOFA Analyze for a Ticker Dive on SIVE. Initialize the workspace, run Stage 0, and prepare frontier options.
```

Sector Hunt:

```text
Use SOFA Analyze for a Sector Hunt on advanced optical interconnect bottlenecks. Keep Sector Hunt conclusions to a ranked queue only.
```

Sector-to-Ultra:

```text
Use the Sector-to-Ultra guide to generate dive_packets for the top ranked companies, then run Ticker Dive on the selected candidate.
```
