# Installation

SOFA is a framework repo. Minimal use does not require installing optional search or financial tools.

> **Interpreter name:** commands below use `python`. On Windows use `python` or `py`; some Linux distros only ship `python3`. Use whichever your system provides.

## Minimal Local Use

Run the commands below from the repository root.

1. Place or clone the repo where your host agent can read it.
2. Use `skills/sofa-analyze/SKILL.md` as the framework entry.
3. Run workspace initialization before research:

```bash
python scripts/init_workspace.py "SUBJECT" "./workspace" --mode ticker
python scripts/init_workspace.py "THEME" "./workspace" --mode sector
```

4. Run gates and validators from `scripts/` as the workflow progresses.

## Optional Native Subagent Setup

SOFA works without native subagent configuration. The default path is still for the main SOFA thread to read the prompt templates, assemble a fresh dispatch packet, and send bounded work to the host agent's subagent mechanism when needed.

Native subagents are optional for frequent users who repeatedly run the same SOFA worker roles, such as Frontier Scout, Sector Mapper, Financial Bridge Analyst, or Red Team. Codex supports custom agents under `.codex/agents/*.toml`, and Claude Code supports custom subagents under `.claude/agents/*.md`. These files can make stable worker roles easier to reuse, but they should be created deliberately and kept reviewable.

Use this decision rule:

| Situation | Recommendation |
| --- | --- |
| First-time use, cross-agent use, or lowest setup friction | Keep the default prompt-template dispatch path. |
| Frequent SOFA use with the same worker roles | Consider native Codex or Claude Code subagents. |
| Asking the host agent to invent subagents during installation | Avoid this; use explicit, reviewable definitions instead. |

If you enable native subagents, keep only stable behavior in the agent definition: role identity, tool or permission boundaries, forbidden conclusions, file-output discipline, and output expectations. The current company, sector, frontier packet, evidence summary, delivery path, method-card paths, and search capability status must still come from the main SOFA thread in each dispatch packet.

Native subagents do not change SOFA's control boundaries. The main thread still owns orchestration, ledgers, gates, workspace state, and final verdicts. Future SOFA releases may provide official Codex and Claude Code subagent templates, but this installation guide does not install or overwrite any local agent configuration.

## Boundaries

SOFA does not silently install optional tools, write credentials, or assume one host runtime. Host-specific mapping belongs in `docs/adapters/`.

## Recommended Checks

```bash
python -m compileall -q scripts tests
python -m unittest discover -s tests -p "test_*.py"
```

## Next Steps

- Configure optional capabilities with `docs/capability-setup.md`.
- Pick the adapter that matches your host environment.
- Start from `SOFA Analyze` and keep evidence, workflow, capability, and claim ledgers inside the active research workspace.
