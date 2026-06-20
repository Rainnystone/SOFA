#!/usr/bin/env python3
"""
Generate Ticker Dive Ultra packets from Sector Hunt candidates.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")
    return slug or "candidate"


def load_candidates(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        candidates = payload["candidates"]
    else:
        raise ValueError("candidate JSON must be a list or an object with a candidates list")

    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("each candidate must be a JSON object")
    return candidates


def render_packet(candidate: dict[str, Any]) -> str:
    company = str(candidate.get("company") or candidate.get("name") or "Unknown Company")
    ticker = str(candidate.get("ticker") or "UNKNOWN")
    candidate_id = str(candidate.get("candidate_id") or "candidate")
    layer = str(candidate.get("layer") or "Unspecified")
    why = str(candidate.get("why_surfaced") or candidate.get("why") or "Not recorded")
    evidence_grade = str(candidate.get("evidence_grade") or "Unrated")
    evidence = _as_list(candidate.get("evidence"))
    open_questions = _as_list(candidate.get("open_questions"))

    return f"""# Ultra Dive Packet: {company}

## Packet Metadata
| Field | Value |
|-------|-------|
| Candidate ID | {candidate_id} |
| Company | {company} |
| Ticker | {ticker} |
| Mode | Ticker Dive Ultra |
| Origin | Sector Hunt ranked target queue |
| Sector Layer | {layer} |
| Inherited Evidence Grade | {evidence_grade} |

Mode: Ticker Dive Ultra

## Sector Hunt Boundary
Sector Hunt produced this candidate for deeper research, but Sector Hunt does not produce an Action Class, final verdict, or investment-style conclusion. This packet is an input to Ticker Dive Ultra, not a conclusion.

## Sector Hunt Rationale
{why}

## Evidence To Carry Forward
{_render_bullets(evidence, "- No evidence entries supplied.")}

## Required Method Cards
- Supply Chain Mapping: validate the dependency layer, bottleneck role, and upstream/downstream exposure.
- Customer Graph Discovery: connect customer adoption, concentration, and demand quality to the candidate.
- Financial Bridge: convert technical relevance into revenue, margin, capex, and valuation questions.
- Red Team: attack the bottleneck thesis, evidence quality, substitution risk, and market-size assumptions.

## Financial Bridge Questions
- Revenue conversion: what specific product, customer, or licensing path turns the Sector Hunt bottleneck into revenue?
- What portion of current revenue already maps to the identified layer?
- Which gross margin, capex, working-capital, or mix effects would confirm the thesis?
- What public filings, segment notes, customer disclosures, or comparable data can validate scale?
- What would make the implied valuation bridge fail?

## Red-Team Attack Surface
- The candidate may be adjacent to the bottleneck rather than economically exposed to it.
- Customer evidence may reflect pilots, design wins, or narrative interest rather than durable revenue.
- Larger incumbents or substitute architectures may compress the candidate's pricing power.
- Public financials may be too thin to support the Sector Hunt implication.
- Timing mismatch may turn a real technical role into a weak investment research conclusion.

## Open Questions
{_render_bullets(open_questions, "- No open questions supplied.")}

## Next Step
Run a full Ticker Dive Ultra workflow before making any action-class style conclusion.
"""


def write_packets(
    workspace: Path, candidates: list[dict[str, Any]], force: bool = False
) -> list[Path]:
    output_dir = workspace / "dive_packets"
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_id = candidate.get("candidate_id") or f"candidate_{index:03d}"
        ticker = (
            candidate.get("ticker")
            or candidate.get("company")
            or candidate.get("name")
            or f"candidate_{index:03d}"
        )
        filename = f"{slugify(candidate_id)}_{slugify(ticker)}_ultra_packet.md"
        path = output_dir / filename
        if path.exists() and not force:
            raise ValueError(f"packet already exists: {path}. Use --force to overwrite.")
        path.write_text(render_packet(candidate), encoding="utf-8")
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Ticker Dive Ultra packets from Sector Hunt candidates"
    )
    parser.add_argument("--workspace", required=True, type=Path, help="SOFA workspace path")
    parser.add_argument(
        "--candidate-json",
        required=True,
        type=Path,
        help="JSON list or object with a candidates list",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing packet files",
    )
    args = parser.parse_args()

    try:
        candidates = load_candidates(args.candidate_json)
        paths = write_packets(args.workspace, candidates, force=args.force)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    else:
        for path in paths:
            print(path)
        return 0


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _render_bullets(values: list[str], empty: str) -> str:
    if not values:
        return empty
    return "\n".join(f"- {value}" for value in values)


if __name__ == "__main__":
    raise SystemExit(main())
