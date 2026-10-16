"""G7: component tolerance analysis.

worst_case (default) — sensitivity-based extreme value analysis:
  1. at nominal supply, perturb each toleranced quantity (part value or model parameter such as a
     regulator's reference) by +tol, one at a time, and record the sign of every criterion's change;
  2. for each criterion and direction (high / low), set every quantity to the extreme that pushes the
     criterion that way;
  3. simulate that combination at the supply corner where the criterion already had the least margin,
     and check all acceptance criteria and derated part ratings.
  Assumes a monotonic response within the tolerance band (standard EVA assumption).

monte_carlo — `samples` random combinations (uniform within tolerance), supply corners in turn; every
  sample must pass. Reports the observed spread.
"""

from __future__ import annotations

import random
from pathlib import Path

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..sim.measure import Waveforms, check_ratings, measure_criterion
from ..sim.ngspice import SimError
from ..sim.pool import SimJob, auto_jobs, run_jobs
from ..sim.spice import Scenario, build_deck
from ..spec import Spec
from .base import Finding, GateResult, Severity, Status, status_from

Item = tuple[str, str, float]  # (ref, "value" | parameter name, relative tolerance)


def tolerance_items(nl: Netlist, db: PartsDB) -> list[Item]:
    items: list[Item] = []
    for ref in sorted(nl.components):
        pd = db.get(nl.components[ref].part_key)
        if pd is None or pd.spice is None or pd.spice.type == "connector":
            continue
        if pd.value == "required" and pd.tolerance:
            items.append((ref, "value", pd.tolerance))
        for name, prm in sorted(pd.spice.params.items()):
            if prm.tolerance:
                items.append((ref, name, prm.tolerance))
    return items


def _label(item: Item, factor: float) -> str:
    ref, key, _ = item
    what = ref if key == "value" else f"{ref}.{key}"
    return f"{what} {factor - 1:+.0%}"


def _evaluate(nl, db, spec, deck, res, factors) -> tuple[dict[str, float | None], list, list[Finding]]:
    """(criterion values, criterion results, rating findings) for one simulation."""
    if isinstance(res, SimError):
        return {}, [], [Finding("tolerance.ngspice", Severity.ERROR, str(res))]
    wf = Waveforms(res, spec)
    if not wf.valid:
        return {}, [], [Finding("tolerance.sim", Severity.ERROR, wf.invalid_reason)]
    measured = [measure_criterion(c, wf) for c in spec.acceptance]
    vals = {m.id: m.value for m in measured}
    bad = [rc for rc in check_ratings(nl, db, deck.simulated, wf, factors) if not rc.passed]
    return (
        vals,
        measured,
        [
            Finding(
                "ratings.tolerance",
                Severity.ERROR,
                f"{rc.ref} ({rc.part}) {rc.rating} reaches {rc.peak:.4g}, allowed "
                + (
                    f"{rc.limit_lo:.4g}..{rc.limit_hi:.4g}"
                    if rc.limit_lo is not None
                    else f"<= {rc.limit_hi:.4g}"
                ),
                refs=[rc.ref],
            )
            for rc in bad
        ],
    )


def run_tolerance(
    nl: Netlist,
    db: PartsDB,
    spec: Spec,
    workdir: Path,
    timeout: int = 300,
    jobs: int | None = None,
    nominal_measurements: dict[str, dict[str, float | None]] | None = None,
) -> GateResult:
    cfg = spec.tolerance
    title = "tolerance analysis"
    if not cfg.enabled:
        return GateResult("G7", title, Status.PASS, notes=["disabled in spec (tolerance.enabled: false)"])
    items = tolerance_items(nl, db)
    if not items:
        return GateResult("G7", title, Status.PASS, notes=["no toleranced parts or parameters"])
    factors = {
        "voltage": spec.derating.voltage,
        "current": spec.derating.current,
        "power": spec.derating.power,
    }
    corners = spec.power_input.corners()
    findings: list[Finding] = []
    rows: list[dict] = []
    envelope: dict[str, list[float]] = {}

    def run(scenarios: list[tuple[str, Scenario]]):
        decks = {name: build_deck(nl, db, spec, sc) for name, sc in scenarios}
        sim_jobs = [SimJob(decks[name].text, workdir / name, timeout) for name, _ in scenarios]
        res = run_jobs(sim_jobs, auto_jobs(len(sim_jobs), jobs))
        return decks, {name: res[workdir / name] for name, _ in scenarios}

    def check(name: str, sc: Scenario, deck, res, desc: str) -> bool:
        n0 = len(findings)
        vals, measured, rating_findings = _evaluate(nl, db, spec, deck, res, factors)
        for m in measured:
            if m.value is not None:
                envelope.setdefault(m.id, []).append(m.value)
            if not m.passed:
                v = "n/a" if m.value is None else f"{m.value:.4g}"
                findings.append(
                    Finding(
                        "tolerance.criterion",
                        Severity.ERROR,
                        f"[{sc.name}; {desc}] {m.id} = {v}, required {m.limit}",
                        hint="Increase the design margin or use tighter-tolerance parts.",
                    )
                )
        for f in rating_findings:
            f.message = f"[{sc.name}; {desc}] {f.message}"
            findings.append(f)
        return len(findings) == n0

    vnom = spec.power_input.v_nom
    if cfg.method == "monte_carlo":
        rng = random.Random(cfg.seed)
        names = list(corners)
        scen = []
        for k in range(cfg.samples):
            pert = {(r, key): 1 + rng.uniform(-t, t) for r, key, t in items}
            cname = names[k % len(names)]
            scen.append(
                (f"mc{k:03d}", Scenario(f"{cname}={corners[cname]:g}V", corners[cname], perturb=pert))
            )
        decks, res = run(scen)
        passed = sum(
            check(name, sc, decks[name], res[name], f"Monte Carlo sample {name[2:]}") for name, sc in scen
        )
        notes = [f"Monte Carlo: {cfg.samples} samples, {passed} passed (seed {cfg.seed})"]
    else:
        # 1) sensitivities at nominal supply
        sens_sc = [("nominal", Scenario(f"vnom={vnom:g}V", vnom))]
        sens_sc += [
            (f"sens_{i:02d}", Scenario(f"vnom={vnom:g}V", vnom, perturb={(r, k): 1 + t}))
            for i, (r, k, t) in enumerate(items)
        ]
        decks, res = run(sens_sc)
        base_vals, _, _ = _evaluate(nl, db, spec, decks["nominal"], res["nominal"], factors)
        if not base_vals:
            return GateResult(
                "G7",
                title,
                Status.FAIL,
                [Finding("tolerance.nominal", Severity.ERROR, "nominal simulation failed")],
            )
        signs: dict[str, list[int]] = {cid: [] for cid in base_vals}
        for i in range(len(items)):
            vals, _, _ = _evaluate(nl, db, spec, decks[f"sens_{i:02d}"], res[f"sens_{i:02d}"], factors)
            for cid, b in base_vals.items():
                v = vals.get(cid)
                if v is None or b is None:
                    signs[cid].append(0)
                else:
                    d = v - b
                    signs[cid].append(0 if abs(d) <= 1e-9 * max(abs(b), 1.0) else (1 if d > 0 else -1))
        # 2) worst-case combinations, each at the supply corner with the least margin
        combos: dict[tuple, tuple[str, str]] = {}
        for c in spec.acceptance:
            cid = c.key()
            for direction, word in ((1, "high"), (-1, "low")):
                pert = tuple(1 + direction * s * t for s, (_, _, t) in zip(signs[cid], items, strict=True))
                per_corner = nominal_measurements or {}
                cands = {sc: m.get(cid) for sc, m in per_corner.items() if m.get(cid) is not None}
                if cands:
                    corner_label = (max if direction > 0 else min)(cands, key=lambda k: cands[k])
                    cname = corner_label.split("=")[0]
                else:
                    cname = "vnom" if "vnom" in corners else next(iter(corners))
                combos.setdefault((pert, cname), (cid, word))
        scen = []
        descs = {}
        for j, ((pert, cname), (cid, word)) in enumerate(combos.items()):
            vin = corners.get(cname, vnom)
            p = {(r, k): f for f, (r, k, _) in zip(pert, items, strict=True)}
            name = f"wc_{j:02d}_{cname}"
            scen.append((name, Scenario(f"{cname}={vin:g}V", vin, perturb=p)))
            changed = [_label(it, f) for f, it in zip(pert, items, strict=True) if abs(f - 1) > 1e-12]
            descs[name] = f"worst-case {word} {cid}: " + (", ".join(changed) or "nominal")
        decks, res = run(scen)
        for name, sc in scen:
            check(name, sc, decks[name], res[name], descs[name])
        notes = [
            f"sensitivity-based worst case: {len(items)} toleranced quantities, "
            f"{len(scen)} worst-case combinations (each at the supply corner with the least margin)"
        ]
    for c in spec.acceptance:
        vals = envelope.get(c.key())
        if not vals:
            continue
        lo, hi = getattr(c, "min", None), getattr(c, "max", None)
        rows.append(
            {
                "id": c.key(),
                "scenario": "tolerance range",
                "value": f"{min(vals):.4g} .. {max(vals):.4g}",
                "limit": f"{'' if lo is None else f'{lo:g}'}..{'' if hi is None else f'{hi:g}'}",
                "passed": (lo is None or min(vals) >= lo) and (hi is None or max(vals) <= hi),
            }
        )
    items_txt = ", ".join(f"{r}{'' if k == 'value' else '.' + k} ±{t:.0%}" for r, k, t in items)
    notes.append(f"toleranced: {items_txt}")
    return GateResult(
        "G7", title, status_from(findings), findings, {"criteria": rows, "method": cfg.method}, notes
    )
