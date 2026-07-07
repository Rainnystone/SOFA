from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1.0"
FRAMING_CONTRACT_FILENAME = "framing_contract.json"
UNKNOWN_ACCEPTED = "unknown-accepted-by-user"

MODES = ("ticker", "sector")
RESOLUTION_METHODS = ("deterministic_quote", "framing_search", "user_confirmed")
RESEARCH_POSTURES = ("fresh", "verify-narrative", "revisit", "compare")
REPORT_LANGUAGES = ("zh", "en", "bilingual")

PREFERENCE_FIELDS = (
    "time_horizon",
    "market_scope",
    "risk_appetite",
    "output_expectation",
    "report_language",
    "budget_appetite",
)
TOP_LEVEL_REQUIRED_FIELDS = ("mode", "research_posture", *PREFERENCE_FIELDS)
SENTINEL_ALLOWED_FIELDS = PREFERENCE_FIELDS
SENTINEL_FORBIDDEN_FIELDS = ("mode", "research_posture", "subject_resolution")
SUBJECT_FIELDS = ("confirmed_name", "tickers", "exchange", "resolution_method", "candidates")


@dataclass(frozen=True)
class FramingIssue:
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class FieldStatus:
    field: str
    status: str
    value: str


@dataclass(frozen=True)
class FramingEvaluation:
    complete: bool
    fields: tuple[FieldStatus, ...]
    issues: tuple[FramingIssue, ...]


class FramingContractError(ValueError):
    pass


def empty_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "subject_resolution": {
            "confirmed_name": "",
            "tickers": [],
            "exchange": "",
            "resolution_method": "",
            "candidates": [],
        },
        "mode": "",
        "research_posture": "",
        "time_horizon": "",
        "market_scope": "",
        "risk_appetite": "",
        "output_expectation": "",
        "report_language": "",
        "budget_appetite": "",
        "clarifications": [],
    }


def normalize_contract(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FramingContractError("framing_contract.json must contain a JSON object.")
    contract = empty_contract()
    for key, value in raw.items():
        if key == "subject_resolution" and isinstance(value, dict):
            subject = dict(contract["subject_resolution"])
            subject.update(value)
            contract["subject_resolution"] = subject
        elif key in contract:
            contract[key] = value
    _assert_shape(contract)
    return contract


def _assert_shape(contract: dict[str, Any]) -> None:
    subject = contract.get("subject_resolution")
    if not isinstance(subject, dict):
        raise FramingContractError("subject_resolution must be a JSON object.")
    for field in SUBJECT_FIELDS:
        if field not in subject:
            raise FramingContractError(f"subject_resolution.{field} is missing.")
    if not isinstance(subject.get("tickers"), list):
        raise FramingContractError("subject_resolution.tickers must be a list.")
    if not isinstance(subject.get("candidates"), list):
        raise FramingContractError("subject_resolution.candidates must be a list.")
    if not isinstance(contract.get("clarifications"), list):
        raise FramingContractError("clarifications must be a list.")


def apply_field(contract: dict[str, Any], field: str, value: str) -> None:
    """Write one top-level framing field.

    apply_field is a pure writer. It validates that the field is a known
    top-level preference/required field, but it does NOT enforce the
    sentinel-forbidden rule — that is evaluate_contract's job (it emits
    FRAMING_SENTINEL_FORBIDDEN). Keeping the forbidden-sentinel check in
    evaluate makes it the single contract authority and avoids a dead-code
    branch that only triggers via hand-edited JSON.
    """
    if field not in TOP_LEVEL_REQUIRED_FIELDS:
        raise FramingContractError(f"Unsupported framing field: {field}")
    if not isinstance(value, str):
        raise FramingContractError(f"{field} value must be a string.")
    if value == UNKNOWN_ACCEPTED:
        # The sentinel is a legal value for preference fields; evaluate owns
        # the forbidden-class check. A whitespace-only value is still rejected
        # below because silent omission encoded as whitespace is never valid.
        pass
    elif value.strip() == "":
        raise FramingContractError(f"{field} value must be a non-empty string.")
    contract[field] = value


def resolve_subject(
    contract: dict[str, Any],
    *,
    name: str,
    tickers: list[str],
    exchange: str,
    method: str,
) -> None:
    if method not in RESOLUTION_METHODS:
        raise FramingContractError(f"Unsupported resolution method: {method}")
    subject = contract["subject_resolution"]
    subject["confirmed_name"] = name
    subject["tickers"] = list(tickers)
    subject["exchange"] = exchange
    subject["resolution_method"] = method


def add_candidate(
    contract: dict[str, Any],
    *,
    name: str,
    ticker: str,
    exchange: str,
    reason_excluded: str,
) -> None:
    """Append one disambiguation candidate.

    All four attributes are required and must be non-empty: the spec says a
    candidate entry is {name, ticker, exchange, reason_excluded} with all
    four present. An empty list means no ambiguity was encountered; a partial
    entry is never valid.
    """
    missing = [
        label
        for label, value in (
            ("name", name),
            ("ticker", ticker),
            ("exchange", exchange),
            ("reason_excluded", reason_excluded),
        )
        if not str(value).strip()
    ]
    if missing:
        raise FramingContractError(
            f"add_candidate requires non-empty: {', '.join(missing)}."
        )
    contract["subject_resolution"]["candidates"].append(
        {
            "name": name,
            "ticker": ticker,
            "exchange": exchange,
            "reason_excluded": reason_excluded,
        }
    )


def add_clarification(contract: dict[str, Any], *, question: str, answer: str) -> None:
    contract["clarifications"].append({"question": question, "answer": answer})


def evaluate_contract(
    contract: dict[str, Any],
    *,
    state_mode: str | None = None,
) -> FramingEvaluation:
    contract = normalize_contract(contract)
    issues: list[FramingIssue] = []
    fields: list[FieldStatus] = []

    _check_schema_version(contract, issues)
    _check_top_level_fields(contract, issues, fields)
    _check_subject_resolution(contract, issues, fields)

    # Mode-drift tripwire: the contract's mode must agree with state.json's
    # mode. A sentinel mode is deliberately excluded here — it is already
    # reported as FRAMING_SENTINEL_FORBIDDEN by _check_top_level_fields, and a
    # value that is not a usable mode should not double-report as drift. A
    # genuine mismatch between two real enum values is the tripwire this
    # catches (user asked for ticker research, state says sector, or vice
    # versa).
    mode = contract.get("mode")
    if state_mode and mode and mode != UNKNOWN_ACCEPTED and mode != state_mode:
        issues.append(
            FramingIssue(
                "FRAMING_MODE_DRIFT",
                "mode",
                f"framing_contract mode '{mode}' does not match state.json mode '{state_mode}'.",
            )
        )

    return FramingEvaluation(complete=not issues, fields=tuple(fields), issues=tuple(issues))


def _check_schema_version(contract: dict[str, Any], issues: list[FramingIssue]) -> None:
    if contract.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            FramingIssue(
                "FRAMING_VALUE_INVALID",
                "schema_version",
                f"schema_version must be {SCHEMA_VERSION}.",
            )
        )


def _check_top_level_fields(
    contract: dict[str, Any],
    issues: list[FramingIssue],
    fields: list[FieldStatus],
) -> None:
    enum_values = {
        "mode": MODES,
        "research_posture": RESEARCH_POSTURES,
        "report_language": REPORT_LANGUAGES,
    }
    for field in TOP_LEVEL_REQUIRED_FIELDS:
        value = contract.get(field, "")
        # Non-string values (hand-edited or generated contracts) cannot be a
        # valid intent field: mark invalid rather than letting them fall
        # through to "complete" and satisfy the Stage 0 gate.
        if not isinstance(value, str):
            issues.append(
                FramingIssue(
                    "FRAMING_VALUE_INVALID",
                    field,
                    f"{field} must be a string.",
                )
            )
            fields.append(FieldStatus(field, "invalid", str(value)))
            continue
        if value.strip() == "":
            issues.append(FramingIssue("FRAMING_FIELD_MISSING", field, f"{field} is required."))
            fields.append(FieldStatus(field, "missing", ""))
            continue
        if value == UNKNOWN_ACCEPTED:
            if field in SENTINEL_ALLOWED_FIELDS:
                fields.append(FieldStatus(field, "unknown-accepted", UNKNOWN_ACCEPTED))
            else:
                issues.append(
                    FramingIssue(
                        "FRAMING_SENTINEL_FORBIDDEN",
                        field,
                        f"{field} cannot use {UNKNOWN_ACCEPTED}.",
                    )
                )
                fields.append(FieldStatus(field, "invalid", UNKNOWN_ACCEPTED))
            continue
        allowed = enum_values.get(field)
        if allowed and value not in allowed:
            issues.append(
                FramingIssue(
                    "FRAMING_VALUE_INVALID",
                    field,
                    f"{field} must be one of: {', '.join(allowed)}.",
                )
            )
            fields.append(FieldStatus(field, "invalid", str(value)))
            continue
        fields.append(FieldStatus(field, "complete", str(value)))


def _check_subject_resolution(
    contract: dict[str, Any],
    issues: list[FramingIssue],
    fields: list[FieldStatus],
) -> None:
    subject = contract["subject_resolution"]
    mode = contract.get("mode")

    confirmed_name = subject.get("confirmed_name", "")
    if not confirmed_name:
        issues.append(
            FramingIssue(
                "FRAMING_FIELD_MISSING",
                "subject_resolution.confirmed_name",
                "subject_resolution.confirmed_name is required.",
            )
        )
        fields.append(FieldStatus("subject_resolution.confirmed_name", "missing", ""))
    else:
        fields.append(FieldStatus("subject_resolution.confirmed_name", "complete", confirmed_name))

    method = subject.get("resolution_method", "")
    if method == UNKNOWN_ACCEPTED:
        issues.append(
            FramingIssue(
                "FRAMING_SENTINEL_FORBIDDEN",
                "subject_resolution.resolution_method",
                "subject_resolution.resolution_method cannot use the unknown-accepted sentinel.",
            )
        )
        fields.append(FieldStatus("subject_resolution.resolution_method", "invalid", method))
    elif method not in RESOLUTION_METHODS:
        issue_code = "FRAMING_FIELD_MISSING" if method == "" else "FRAMING_VALUE_INVALID"
        issues.append(
            FramingIssue(
                issue_code,
                "subject_resolution.resolution_method",
                "subject_resolution.resolution_method must be deterministic_quote, framing_search, or user_confirmed.",
            )
        )
        fields.append(FieldStatus("subject_resolution.resolution_method", "missing" if method == "" else "invalid", method))
    else:
        fields.append(FieldStatus("subject_resolution.resolution_method", "complete", method))

    tickers = [str(item) for item in subject.get("tickers", []) if str(item).strip()]
    exchange = str(subject.get("exchange", ""))
    if mode == "ticker":
        if not tickers:
            issues.append(
                FramingIssue(
                    "FRAMING_FIELD_MISSING",
                    "subject_resolution.tickers",
                    "ticker mode requires at least one resolved ticker.",
                )
            )
            fields.append(FieldStatus("subject_resolution.tickers", "missing", ""))
        else:
            fields.append(FieldStatus("subject_resolution.tickers", "complete", ", ".join(tickers)))
        if not exchange:
            issues.append(
                FramingIssue(
                    "FRAMING_FIELD_MISSING",
                    "subject_resolution.exchange",
                    "ticker mode requires an exchange.",
                )
            )
            fields.append(FieldStatus("subject_resolution.exchange", "missing", ""))
        else:
            fields.append(FieldStatus("subject_resolution.exchange", "complete", exchange))
    else:
        fields.append(FieldStatus("subject_resolution.tickers", "complete", ", ".join(tickers)))
        fields.append(FieldStatus("subject_resolution.exchange", "complete", exchange))
