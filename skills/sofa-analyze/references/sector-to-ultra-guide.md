# Sector-to-Ultra Guide

Sector-to-Ultra converts a completed Sector Hunt ranked queue into one or more Ticker Dive Ultra packets. It is a bridge, not a shortcut around evidence gates.

## Trigger

Use this guide only after Sector Hunt has produced:

- dependency ladder;
- chokepoint matrix;
- ranked target queue;
- Dive Readiness Score for each candidate;
- open questions and suggested first frontier.

If those artifacts are missing, return to Sector Hunt and complete the map before creating Ultra packets.

## Boundary

Sector Hunt does not produce Action Class. It produces a map and ranked queue.

Ultra Mode still requires:

- financial bridge;
- formal red-team;
- catalyst clock;
- invalidation conditions;
- final report gate.

Do not describe a Sector Hunt candidate as Act, Watch, Reject, or any other action-class conclusion before the Ultra Dive completes those requirements.

## Inputs

Use the ranked queue or a JSON candidate list. Each candidate should include:

- company or ticker;
- layer;
- why surfaced;
- evidence grade;
- Dive Readiness Score;
- key inherited evidence;
- open questions;
- suggested first frontier.

## Output

Write Ultra packets under:

```text
{WORKSPACE}/dive_packets/
```

Each packet should contain:

1. candidate identity;
2. inherited Sector Hunt rationale;
3. inherited evidence grade and evidence gaps;
4. first frontier plan;
5. required method cards;
6. financial bridge requirements;
7. red-team attack surface;
8. open questions;
9. explicit statement that the packet is not an action-class conclusion.

## Recommended Script

```bash
python {PLUGIN_DIR}/scripts/generate_ultra_packet.py --workspace "{WORKSPACE}" --candidate-json "{CANDIDATES_JSON}"
```

Use `--force` only when the user intentionally wants to replace existing packets.

## Handoff To Ultra Dive

After a packet exists, start a Ticker Dive workspace or continue in an Ultra-mode workspace using that packet as the intake frontier. The main thread should preserve the inherited map context while still requiring fresh company-level evidence, financial bridge, and red-team checks.

## Completion Check

The bridge is complete when:

- packets exist in `dive_packets/`;
- each packet has a candidate, rationale, evidence grade, and open questions;
- no packet contains action-class language;
- `research_workflow.md` records which Sector Hunt queue item was converted.
