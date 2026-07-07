from __future__ import annotations

from typing import Any

try:
    from .model import FieldStatus, evaluate_contract
except ImportError:
    from model import FieldStatus, evaluate_contract


def render_contract_markdown(contract: dict[str, Any]) -> str:
    evaluation = evaluate_contract(contract)
    subject = contract["subject_resolution"]
    lines = [
        "| Field | Status | Value |",
        "| --- | --- | --- |",
    ]
    for field in evaluation.fields:
        lines.append(f"| {field.field} | {field.status} | {_escape(field.value)} |")

    lines.extend(
        [
            "",
            "### Subject Resolution",
            "",
            f"- Confirmed name: {_inline(subject.get('confirmed_name', ''))}",
            f"- Tickers: {_inline(', '.join(str(item) for item in subject.get('tickers', [])))}",
            f"- Exchange: {_inline(subject.get('exchange', ''))}",
            f"- Resolution method: {_inline(subject.get('resolution_method', ''))}",
            "",
            "### Disambiguation Candidates",
            "",
            "| Name | Ticker | Exchange | Reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    candidates = subject.get("candidates", [])
    if candidates:
        for candidate in candidates:
            lines.append(
                "| {name} | {ticker} | {exchange} | {reason_excluded} |".format(
                    name=_escape(str(candidate.get("name", ""))),
                    ticker=_escape(str(candidate.get("ticker", ""))),
                    exchange=_escape(str(candidate.get("exchange", ""))),
                    reason_excluded=_escape(str(candidate.get("reason_excluded", ""))),
                )
            )
    else:
        lines.append("|  |  |  |  |")

    lines.extend(["", "### Clarifications", "", "| Question | Answer |", "| --- | --- |"])
    clarifications = contract.get("clarifications", [])
    if clarifications:
        for clarification in clarifications:
            lines.append(
                "| {question} | {answer} |".format(
                    question=_escape(str(clarification.get("question", ""))),
                    answer=_escape(str(clarification.get("answer", ""))),
                )
            )
    else:
        lines.append("|  |  |")

    if evaluation.issues:
        lines.extend(["", "### Contract Issues", "", "| Code | Field | Message |", "| --- | --- | --- |"])
        for issue in evaluation.issues:
            lines.append(f"| {issue.code} | {issue.field} | {_escape(issue.message)} |")
    return "\n".join(lines).rstrip() + "\n"


def _inline(value: Any) -> str:
    text = str(value)
    return text if text else ""


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
