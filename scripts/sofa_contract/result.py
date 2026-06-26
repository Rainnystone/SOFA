from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContractIssue:
    code: str
    severity: str
    message: str
    path: str
    evidence: str = ""

    def display(self) -> str:
        detail = f"{self.code}: {self.message} [{self.path}]"
        if self.evidence:
            return f"{detail} - {self.evidence}"
        return detail


@dataclass(frozen=True)
class ContractProfile:
    mode: str | None = None
    target: str = "workspace"
    from_stage: str | None = None
    to_stage: str | None = None


@dataclass
class ContractResult:
    failures: list[ContractIssue] = field(default_factory=list)
    warnings: list[ContractIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, code: str, message: str, path: str, evidence: str = "") -> None:
        self.failures.append(
            ContractIssue(
                code=code,
                severity="fail",
                message=message,
                path=path,
                evidence=evidence,
            )
        )

    def warn(self, code: str, message: str, path: str, evidence: str = "") -> None:
        self.warnings.append(
            ContractIssue(
                code=code,
                severity="warn",
                message=message,
                path=path,
                evidence=evidence,
            )
        )

    def extend(self, other: "ContractResult") -> None:
        self.failures.extend(other.failures)
        self.warnings.extend(other.warnings)
