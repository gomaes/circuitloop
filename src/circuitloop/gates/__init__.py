"""Verification gates. All pass/fail decisions are deterministic Python.

G1 build  -> G2 ERC -> G3 simulation [-> G4 regression -> G5 fault injection]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..report import VerificationReport
from ..spec import Spec
from .base import GateResult, Status
from .g1_build import run_g1
from .g2_erc import run_g2
from .g3_sim import SimOutput, run_faults, run_g3, run_regression


@dataclass
class VerifyContext:
    spec: Spec
    db: PartsDB
    project_dir: Path
    parts_path: str | None = None
    design_timeout: int = 120
    sim_timeout: int = 300


@dataclass
class VerifyOutcome:
    report: VerificationReport
    netlist: Netlist | None = None
    netlist_path: Path | None = None
    sim: SimOutput | None = None
    measurements: dict = field(default_factory=dict)


def verify(
    design: Path,
    workdir: Path,
    ctx: VerifyContext,
    phase: int = 1,
    baseline: dict | None = None,
    faults: bool = False,
    phase_label: str | None = None,
) -> VerifyOutcome:
    rep = VerificationReport(design=str(design), phase=phase_label or f"phase {phase}")
    g1 = run_g1(design, workdir / "build", ctx.spec, ctx.project_dir, ctx.parts_path, ctx.design_timeout)
    rep.gates.append(g1.result)
    later = ["G2", "G3"] + (["G4"] if baseline is not None else []) + (["G5"] if faults else [])
    if not g1.result.passed or g1.netlist is None:
        rep.gates += [GateResult(g, "", Status.SKIPPED) for g in later]
        rep.unverified.append("everything after G1 (design did not build)")
        return VerifyOutcome(rep)
    nl = g1.netlist
    rep.gates.append(run_g2(nl, ctx.db, ctx.spec, phase, g1.skidl_erc, ctx.project_dir))
    sim = run_g3(nl, ctx.db, ctx.spec, workdir / "sim", ctx.sim_timeout)
    rep.gates.append(sim.result)
    if sim.result.status == Status.INCOMPLETE or any(f.rule == "sim.incomplete" for f in sim.result.findings):
        rep.unverified += [f.message for f in sim.result.findings if f.rule == "sim.incomplete"]
    rep.unverified += [n for n in sim.result.notes]
    if baseline is not None:
        rep.gates.append(run_regression(sim.measurements, baseline, sim.result, ctx.spec))
    if faults:
        rep.gates.append(run_faults(nl, ctx.db, ctx.spec, workdir / "faults", ctx.sim_timeout))
    return VerifyOutcome(rep, nl, g1.netlist_path, sim, sim.measurements)
