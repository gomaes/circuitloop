"""Verification report: structured JSON + human-readable Markdown."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .results import GateResult, Severity, Status


@dataclass
class VerificationReport:
    design: str
    phase: str
    gates: list[GateResult] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.status == Status.PASS for g in self.gates)

    def gate(self, name: str) -> GateResult | None:
        return next((g for g in self.gates if g.gate == name), None)

    def to_dict(self) -> dict:
        return {
            "design": self.design,
            "phase": self.phase,
            "passed": self.passed,
            "gates": [g.to_dict() for g in self.gates],
            "unverified": self.unverified,
        }

    def to_markdown(self) -> str:
        icon = {"pass": "PASS", "fail": "FAIL", "incomplete": "INCOMPLETE", "skipped": "SKIPPED"}
        lines = [
            f"# Verification report — {self.phase}",
            "",
            f"- design: `{self.design}`",
            f"- result: **{'PASSED' if self.passed else 'FAILED'}**",
            "",
            "| gate | status | errors | warnings |",
            "|---|---|---|---|",
        ]
        for g in self.gates:
            ne = sum(f.severity == Severity.ERROR for f in g.findings)
            nw = sum(f.severity == Severity.WARNING for f in g.findings)
            lines.append(f"| {g.gate} {g.title} | {icon[str(g.status)]} | {ne} | {nw} |")
        for g in self.gates:
            if not g.findings and not g.notes and not g.metrics.get("criteria"):
                continue
            lines += ["", f"## {g.gate} {g.title} — {icon[str(g.status)]}", ""]
            for f in sorted(g.findings, key=lambda f: ["error", "warning", "info"].index(str(f.severity))):
                where = ", ".join(f.refs + [f"net {n}" for n in f.nets])
                lines.append(
                    f"- **{str(f.severity).upper()}** `{f.rule}`: {f.message}"
                    + (f" ({where})" if where else "")
                )
                if f.hint:
                    lines.append(f"  - hint: {f.hint}")
            crit = g.metrics.get("criteria")
            if crit:
                lines += ["", "| criterion | scenario | value | limit | result |", "|---|---|---|---|---|"]
                for c in crit:
                    lines.append(
                        f"| {c['id']} | {c['scenario']} | {_fmt(c.get('value'))} | {c['limit']} | "
                        f"{'ok' if c['passed'] else 'FAIL'} |"
                    )
            for n in g.notes:
                lines.append(f"- note: {n}")
        if self.unverified:
            lines += ["", "## Not verified", ""] + [f"- {u}" for u in self.unverified]
        return "\n".join(lines) + "\n"

    def write(self, directory: Path, stem: str = "report") -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        j = directory / f"{stem}.json"
        m = directory / f"{stem}.md"
        j.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        m.write_text(self.to_markdown())
        return j, m


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)
