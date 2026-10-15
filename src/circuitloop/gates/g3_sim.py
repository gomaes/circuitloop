"""G3 simulation, G4 regression and G5 fault-injection gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..sim.measure import RatingCheck, Waveforms, check_ratings, measure_criterion
from ..sim.ngspice import SimError, run_ngspice
from ..sim.spice import SRC, Scenario, build_deck
from ..spec import Spec
from .base import Finding, GateResult, Severity, Status, status_from


@dataclass
class SimOutput:
    result: GateResult
    measurements: dict[str, dict[str, float | None]] = field(default_factory=dict)
    waveforms: dict[str, Waveforms] = field(default_factory=dict)


def _rating_finding(rc: RatingCheck, mode: str) -> Finding:
    lim = f"{rc.limit_lo:.4g}..{rc.limit_hi:.4g}" if rc.limit_lo is not None else f"<= {rc.limit_hi:.4g}"
    return Finding(
        f"ratings.{mode}",
        Severity.ERROR,
        f"{rc.ref} ({rc.part}) {rc.rating} reaches {rc.peak:.4g}, allowed {lim}",
        refs=[rc.ref],
        hint="Choose a part with a higher rating or reduce the stress (spec.derating applies in normal "
        "operation; absolute maximum under faults).",
    )


def _deck_notes(deck, spec: Spec, findings: list[Finding], notes: list[str]) -> bool:
    """Record model coverage. Returns True when the simulation is incomplete."""
    for ref, note in deck.equivalent:
        notes.append(f"{ref}: simulated with an equivalent model — {note}")
    if deck.connectors:
        notes.append(
            f"connectors treated as ideal wiring (not rated in simulation): {', '.join(deck.connectors)}"
        )
    if deck.missing_model:
        sev = Severity.WARNING if spec.allow_incomplete_sim else Severity.ERROR
        findings.append(
            Finding(
                "sim.incomplete",
                sev,
                f"no SPICE or equivalent model for {', '.join(deck.missing_model)}: simulation is INCOMPLETE",
                refs=list(deck.missing_model),
                hint="Add a spice: entry (primitive/subckt/equivalent) for these parts in the parts DB.",
            )
        )
        return True
    return False


def run_g3(nl: Netlist, db: PartsDB, spec: Spec, workdir: Path, timeout: int = 300) -> SimOutput:
    findings: list[Finding] = []
    notes: list[str] = []
    criteria: list[dict] = []
    ratings: list[dict] = []
    out = SimOutput(GateResult("G3", "simulation", Status.PASS))
    factors = {
        "voltage": spec.derating.voltage,
        "current": spec.derating.current,
        "power": spec.derating.power,
    }
    incomplete = False
    for name, vin in spec.power_input.corners().items():
        sc = Scenario(name=f"{name}={vin:g}V", vin=vin)
        deck = build_deck(nl, db, spec, sc)
        if name == next(iter(spec.power_input.corners())):
            incomplete = _deck_notes(deck, spec, findings, notes)
        try:
            simres = run_ngspice(deck.text, workdir / name, timeout)
        except SimError as e:
            findings.append(
                Finding(
                    "sim.ngspice",
                    Severity.ERROR,
                    f"[{sc.name}] {e}",
                    hint="Check for floating nodes or impossible connections.",
                )
            )
            continue
        wf = Waveforms(simres, spec)
        if not wf.valid:
            findings.append(
                Finding(
                    "sim.op",
                    Severity.ERROR,
                    f"[{sc.name}] DC operating point did not converge",
                    hint="Look for floating nodes or positive feedback without hysteresis.",
                )
            )
            continue
        out.waveforms[sc.name] = wf
        out.measurements[sc.name] = {}
        for c in spec.acceptance:
            m = measure_criterion(c, wf)
            out.measurements[sc.name][m.id] = m.value
            criteria.append(
                {
                    "id": m.id,
                    "scenario": sc.name,
                    "value": m.value,
                    "limit": m.limit,
                    "passed": m.passed,
                    "detail": m.detail,
                }
            )
            if not m.passed:
                val = "n/a" if m.value is None else f"{m.value:.4g}"
                findings.append(
                    Finding(
                        "sim.criterion",
                        Severity.ERROR,
                        f"[{sc.name}] {m.id} = {val}, required {m.limit}"
                        + (f" ({m.detail})" if m.detail else ""),
                    )
                )
        for rc in check_ratings(nl, db, deck.simulated, wf, factors):
            ratings.append({"scenario": sc.name, **rc.__dict__})
            if not rc.passed:
                findings.append(_rating_finding(rc, "derating"))
    out.result.findings = findings
    out.result.notes = notes
    out.result.metrics = {"criteria": criteria, "ratings": ratings, "measurements": out.measurements}
    st = status_from(findings)
    if st == Status.PASS and incomplete and not spec.allow_incomplete_sim:
        st = Status.INCOMPLETE
    if (
        st == Status.FAIL
        and incomplete
        and not any(f.rule != "sim.incomplete" for f in findings if f.severity == Severity.ERROR)
    ):
        st = Status.INCOMPLETE
    out.result.status = st
    return out


def run_faults(nl: Netlist, db: PartsDB, spec: Spec, workdir: Path, timeout: int = 300) -> GateResult:
    findings: list[Finding] = []
    criteria: list[dict] = []
    notes: list[str] = []
    faults = spec.effective_faults()
    if not faults:
        return GateResult("G5", "fault injection", Status.PASS, notes=["no faults defined in spec"])
    abs_max = {"voltage": 1.0, "current": 1.0, "power": 1.0}
    for f in faults:
        vin = f.voltage if f.voltage is not None else spec.power_input.v_nom
        sc = Scenario(name=f"fault:{f.name}", vin=vin, fault=f)
        deck = build_deck(nl, db, spec, sc)
        if deck.missing_model:
            findings.append(
                Finding(
                    "fault.incomplete",
                    Severity.ERROR,
                    f"[{sc.name}] cannot verify: no model for {', '.join(deck.missing_model)}",
                )
            )
            continue
        try:
            simres = run_ngspice(deck.text, workdir / f.name, timeout)
        except SimError as e:
            findings.append(Finding("fault.ngspice", Severity.ERROR, f"[{sc.name}] {e}"))
            continue
        wf = Waveforms(simres, spec)
        if not wf.valid:
            findings.append(
                Finding(
                    "fault.op",
                    Severity.ERROR,
                    f"[{sc.name}] DC operating point did not converge; fault not verified",
                )
            )
            continue
        for net, lim in sorted(f.expect.nets.items()):
            v = wf.v_net(net)
            lo_v = None if v is None else float(np.min(v))
            hi_v = None if v is None else float(np.max(v))
            ok = (
                v is not None
                and (lim.min is None or lo_v >= lim.min)
                and (lim.max is None or hi_v <= lim.max)
            )
            val = None if v is None else (lo_v if lim.min is not None and lo_v < lim.min else hi_v)
            limit = f"{'' if lim.min is None else lim.min}..{'' if lim.max is None else lim.max} V"
            criteria.append(
                {"id": f"V({net})", "scenario": sc.name, "value": val, "limit": limit, "passed": ok}
            )
            if not ok:
                findings.append(
                    Finding(
                        "fault.net",
                        Severity.ERROR,
                        f"[{sc.name}] V({net}) = {val if val is None else round(val, 4)} V, required {limit}",
                        nets=[net],
                    )
                )
        if f.expect.max_input_current is not None:
            i = wf.i(SRC)
            val = float(np.max(np.abs(i))) if i is not None else None
            ok = val is not None and val <= f.expect.max_input_current
            criteria.append(
                {
                    "id": "|I(input)|",
                    "scenario": sc.name,
                    "value": val,
                    "limit": f"<= {f.expect.max_input_current:g} A",
                    "passed": ok,
                }
            )
            if not ok:
                findings.append(
                    Finding(
                        "fault.input_current",
                        Severity.ERROR,
                        f"[{sc.name}] input current {val} A exceeds {f.expect.max_input_current} A",
                    )
                )
        if f.expect.abs_max_ratings:
            bad = [rc for rc in check_ratings(nl, db, deck.simulated, wf, abs_max) if not rc.passed]
            criteria.append(
                {
                    "id": "abs-max ratings",
                    "scenario": sc.name,
                    "value": len(bad),
                    "limit": "0 violations",
                    "passed": not bad,
                }
            )
            for rc in bad:
                fd = _rating_finding(rc, "absolute_max")
                fd.message = f"[{sc.name}] " + fd.message
                fd.hint = "Add/strengthen protection so this part survives the fault condition."
                findings.append(fd)
    return GateResult("G5", "fault injection", status_from(findings), findings, {"criteria": criteria}, notes)


def run_regression(
    current: dict[str, dict[str, float | None]],
    baseline: dict[str, dict[str, float | None]],
    g3: GateResult,
    spec: Spec,
) -> GateResult:
    findings: list[Finding] = []
    criteria = []
    drift = spec.regression.max_drift
    for sc, vals in sorted(baseline.items()):
        for cid, base in sorted(vals.items()):
            now = current.get(sc, {}).get(cid)
            crit = next(
                (c for c in g3.metrics.get("criteria", []) if c["id"] == cid and c["scenario"] == sc), None
            )
            within = bool(crit and crit["passed"])
            rel = None
            if base is not None and now is not None and abs(base) > 1e-12:
                rel = abs(now - base) / abs(base)
            ok = within and (drift is None or (rel is not None and rel <= drift))
            criteria.append(
                {
                    "id": cid,
                    "scenario": sc,
                    "value": now,
                    "limit": f"baseline {base if base is None else round(base, 5)}"
                    + (f", drift <= {drift:.0%}" if drift else "")
                    + ", within acceptance",
                    "passed": ok,
                }
            )
            if not ok:
                reason = (
                    "outside acceptance" if not within else f"drifted {rel if rel is None else f'{rel:.1%}'}"
                )
                findings.append(
                    Finding(
                        "regression",
                        Severity.ERROR,
                        f"[{sc}] {cid}: {reason} (Phase 1: {base}, now: {now})",
                        hint="Protection must not break the original function.",
                    )
                )
    if not baseline:
        findings.append(Finding("regression", Severity.ERROR, "no Phase 1 baseline available"))
    return GateResult("G4", "regression vs Phase 1", status_from(findings), findings, {"criteria": criteria})


def summarize_waveforms(sim: SimOutput, nets: list[str]) -> dict[str, dict[str, list[float]]]:
    """Downsampled transient traces for plotting."""
    out: dict[str, dict[str, list[float]]] = {}
    for sc, wf in sim.waveforms.items():
        plot = wf.plots.get("tran")
        if plot is None or plot.time is None:
            continue
        step = max(1, len(plot.time) // 4000)
        d = {"time": plot.time[::step].tolist()}
        for n in nets:
            tv = wf.full_tran(n)
            if tv is not None:
                d[n] = np.asarray(tv[1])[::step].tolist()
        out[sc] = d
    return out
