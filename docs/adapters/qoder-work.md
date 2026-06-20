# Qoder-Compatible Workspace Adapter

## Mapping

| SOFA concept | Qoder-compatible mapping |
|--------------|--------------------|
| Main thread | Host main conversation |
| Host progress tracker | Host todo tracker plus workspace files |
| Host subagent mechanism | Host task dispatch tool |
| User clarification | Host clarification UI |
| Search/fetch | Host web search and fetch tools, plus configured AnySearch/Exa/Tavily |
| User-level config | Host-specific config path when the host uses one |

## Start Examples

Ticker Dive:

```text
Use SOFA Analyze as a Ticker Dive. Run init_workspace.py first, use host web search and fetch tools only according to search-strategy, and keep Scout workers isolated.
```

Sector Hunt:

```text
Use SOFA Analyze for a Sector Hunt. Dispatch Sector Mapper through Task, then dispatch Coverage Challenge after the mapper output lands on disk.
```

Sector-to-Ultra:

```text
After the ranked queue is complete, generate Ultra packets under dive_packets and do not assign Action Class until Ultra Dive finishes financial bridge and red-team.
```
