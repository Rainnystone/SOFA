# ZCode Adapter

## Mapping

| SOFA concept | ZCode mapping |
|--------------|---------------|
| Main thread | Current ZCode conversation |
| Host progress tracker | `TodoWrite` tool plus project planning files |
| Host subagent mechanism | `Agent` tool with `subagent_type`, such as the built-in `general-purpose` or `Explore` profile; dynamic, profile-based dispatch |
| User clarification | `AskUserQuestion` tool |
| Search/fetch | `WebSearch` and `WebFetch` tools, or configured Exa MCP / web reader capabilities |
| File editing | `Read`, `Edit`, and `Write` for files; `Bash` for verification |
| Verification | Terminal commands through `Bash` |

## Subagent Dispatch

ZCode dispatches subagents dynamically through the `Agent` tool with a `subagent_type` profile (for example the built-in `general-purpose` or `Explore` profile). There is no static native-agent definition file to install, so SOFA workers in ZCode follow the default prompt-template dispatch path: the main thread reads the relevant worker prompt from `scripts/prompts/`, assembles a bounded packet, and sends it to a worker through the `Agent` tool. The worker writes its full output to the assigned delivery file and returns only a summary. The SOFA control boundaries stay unchanged: the main thread still owns orchestration, ledgers, gates, workspace state, and final verdicts.

## Start Examples

Ticker Dive:

```text
Use SOFA Analyze for a Ticker Dive on the named company. Initialize the workspace with init_workspace.py, run Stage 0 framing, and present the provisional frontiers for direction selection.
```

Sector Hunt:

```text
Use SOFA Analyze for a Sector Hunt on the named technology theme. Produce the dependency ladder, chokepoint matrix, and ranked queue, and keep Sector Hunt conclusions to a ranked queue only.
```

Sector-to-Ultra:

```text
After the ranked queue is complete, use the Sector-to-Ultra guide to generate Ultra packets under dive_packets, then run a full Ticker Dive on the selected candidate.
```
