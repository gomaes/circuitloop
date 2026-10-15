"""Common result types for verification gates (kept outside gates/ to avoid import cycles).

Every gate is deterministic Python and returns a :class:`GateResult`. Pass/fail
is decided here, never by an LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"  # could not fully verify (e.g. missing SPICE model)
    SKIPPED = "skipped"  # not run because an earlier gate failed


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    refs: list[str] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    hint: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = str(self.severity)
        return d


@dataclass
class GateResult:
    gate: str
    title: str
    status: Status
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == Status.PASS

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "title": self.title,
            "status": str(self.status),
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
            "notes": self.notes,
        }


def status_from(findings: list[Finding]) -> Status:
    return Status.FAIL if any(f.severity == Severity.ERROR for f in findings) else Status.PASS
