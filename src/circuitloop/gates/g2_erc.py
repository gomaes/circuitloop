"""G2: SKiDL ERC + pluggable circuitloop rules."""

from __future__ import annotations

from pathlib import Path

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..rules import RuleContext, load_rules
from ..spec import Spec
from .base import Finding, GateResult, Severity, status_from


def run_g2(
    netlist: Netlist,
    db: PartsDB,
    spec: Spec,
    phase: int,
    skidl_erc: list[tuple[str, str]],
    project_dir: Path | None,
) -> GateResult:
    ctx = RuleContext(netlist, db, spec, phase, skidl_erc)
    findings: list[Finding] = []
    ran = []
    for r in load_rules(project_dir):
        if phase < r.min_phase:
            continue
        ran.append(r.id)
        try:
            findings += r(ctx)
        except Exception as e:  # a broken plugin must not silently pass
            findings.append(Finding(r.id, Severity.ERROR, f"rule crashed: {type(e).__name__}: {e}"))
    return GateResult("G2", "ERC", status_from(findings), findings, {"rules": ran})
