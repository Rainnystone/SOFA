# Method Card Spec

SOFA method cards are private research technique cards for subagents. They borrow the progressive disclosure style of agent skills, but they are not user-invocable skills.

## Required Metadata

Each method card must use YAML frontmatter as the single authoritative metadata source. Do not duplicate metadata in fenced YAML blocks in the body.

```yaml
---
name: card-name
description: short card purpose and routing summary
visibility: subagent-private
owner_agent: stable-agent-slug
owner_agent_label: Display Agent Name
load_when: specific packet condition
inputs: packet fields required by this card
outputs: file sections the subagent must produce
forbidden_uses: ways this card must not be used
---
```

`owner_agent` is a stable slug for routing and durable references. `owner_agent_label` is the human-readable display name used in tables, prompts, and reports.

## Loading Contract

- The main-thread packet always has priority over the method card.
- The card defines research technique, not the research objective.
- The subagent loads only the card or cards required by the packet.
- The subagent writes its answer to the assigned workspace file.
- The subagent returns a short summary to the main thread and preserves detailed evidence in the file.
- The subagent output must declare `Method cards loaded: [...]`.

## Path Contract

- Method card references must point to `method-cards/<card>/METHOD.md`.
- Do not reference legacy method directories as skill files.
- Method card files are private `METHOD.md` resources, not user-invocable skill entrypoints.

## User Boundary

Users should not call method cards directly. Direct calls skip SOFA's routing, evidence ledger, gate checks, financial bridge, and red-team requirements.
