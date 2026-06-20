# Architecture

SOFA is a host-neutral framework repo with thin host adapters.

## Layers

| Layer | Purpose |
|-------|---------|
| SOFA Analyze | Router and main-thread orchestration for Ticker Dive, Sector Hunt, and Sector-to-Ultra. |
| Mode guides | Detailed workflow steps for each research mode. |
| Method cards | Subagent-private methods for mapping, customer graph, financial bridge, and red-team work. |
| Prompt templates | Standalone worker instructions in `scripts/prompts/`. |
| Deterministic scripts | Workspace setup, gates, capability checks, validators, and Ultra packet generation. |
| Adapters | Host-specific mapping for Codex, Claude Code, Qoder-compatible workspaces, and generic agents. |

## Boundary

Core files must not depend on a single host tool name, host todo tracker, host web search tool, host web fetch tool, or host-specific config path. Those details belong in adapter docs or this architecture overview.

Search and financial capabilities are optional. SOFA detects them, recommends setup, and records missing capability effects on confidence.

Sector Hunt ends with a map and ranked queue. Ticker Dive or Ultra Dive is required before action-class conclusions.
