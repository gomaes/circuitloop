"""Infeasible tolerance windows: honest report (exit 4) and the minimal automatic relaxation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from rich.console import Console

from circuitloop import EXIT_DESIGN_FAILED, EXIT_OK, EXIT_SPEC_INFEASIBLE
from circuitloop.agents.mock import MockBackend
from circuitloop.config import Config
from circuitloop.feasibility import assess
from circuitloop.orchestrator import Orchestrator, RunState, latest_run
from circuitloop.partsdb import load_db
from circuitloop.relax import edit_text, run_with_relaxation
from circuitloop.spec import load_spec

from .conftest import FIXTURES, needs_ngspice
from .helpers import EXAMPLES, reference, run_design

SPEC_TEXT = """\
name: osc
description: test   # keep this comment
power_input: {v_min: 9, v_nom: 12, v_max: 13}
transient: {stop: 0.01, step: 1.0e-6, settle: 0.005}
acceptance:
  - type: frequency
    net: OUT        # oscillator output
    min: 900        # -10 %
    max: 1100
  - type: input_power
    max: 0.5
assumptions:
  - "first assumption"
"""

CHANGES = [
    {"criterion": "frequency_OUT", "field": "min", "old": 900, "new": 887},
    {"criterion": "frequency_OUT", "field": "max", "old": 1100, "new": 1112},
]


def test_edit_text_keeps_comments_and_records_assumption():
    out = edit_text(SPEC_TEXT, CHANGES, "relaxed: 900..1100 -> 887..1112")
    assert "min: 887        # -10 %" in out and "max: 1112\n" in out
    assert "# keep this comment" in out and "# oscillator output" in out
    data = yaml.safe_load(out)
    assert data["assumptions"] == ["first assumption", "relaxed: 900..1100 -> 887..1112"]
    assert data["acceptance"][1] == {"type": "input_power", "max": 0.5}


def test_edit_text_adds_assumptions_section_and_falls_back_on_flow_style():
    no_asm = SPEC_TEXT.split("assumptions:")[0]
    out = edit_text(no_asm, CHANGES, "note")
    assert yaml.safe_load(out)["assumptions"] == ["note"] and "# oscillator output" in out
    flow = SPEC_TEXT.replace('assumptions:\n  - "first assumption"\n', "assumptions: [a]\n")
    data = yaml.safe_load(edit_text(flow, CHANGES, "note"))  # re-dumped: values still right
    assert data["assumptions"] == ["a", "note"] and data["acceptance"][0]["min"] == 887


def _narrow(tmp_path: Path, lo: float, hi: float, forbid_tighter: bool = True) -> Path:
    spec = yaml.safe_load((EXAMPLES / "ne555_blinker" / "spec.yaml").read_text())
    spec["acceptance"][0].update(min=lo, max=hi)
    if forbid_tighter:  # the reference design then already uses the tightest allowed parts
        db = load_db()
        spec["parts_policy"]["forbidden"] = [
            k
            for k in db.keys()
            if db[k].kind in ("resistor", "capacitor", "electrolytic")
            and (db[k].tolerance or 1) < (0.01 if db[k].kind == "resistor" else 0.1)
        ]
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec, sort_keys=False))
    return p


@needs_ngspice
def test_assess_infeasible_window(tmp_path):
    p = _narrow(tmp_path, 0.97, 1.03)
    out = run_design(
        tmp_path / "d",
        "ne555_blinker",
        reference("ne555_blinker", "hardened"),
        phase=3,
        faults=True,
        spec_path=p,
    )
    fz = assess(out.report, load_spec(p), load_db())
    assert fz.eligible and fz.stop_now
    (chk,) = fz.checks
    assert chk.verdict == "infeasible" and chk.spread > 0.06
    assert chk.relaxed_lo <= chk.lo and chk.relaxed_hi >= chk.hi  # covers the verified range ...
    assert chk.relaxed_lo > chk.lo - 0.002 and chk.relaxed_hi < chk.hi + 0.002  # ... and no more
    assert any(d["topic"] == "tolerance.infeasible" for d in out.report.diagnosis)


@needs_ngspice
def test_assess_recenter_is_not_infeasible(tmp_path):
    out = run_design(
        tmp_path / "d",
        "ne555_blinker",
        reference("ne555_blinker", "hardened"),
        phase=3,
        faults=True,
        spec_path=_narrow(tmp_path, 0.93, 1.27),  # wide enough, but off-centre
    )
    fz = assess(out.report, load_spec(tmp_path / "spec.yaml"), load_db())
    assert fz.checks[0].verdict == "recenter" and fz.checks[0].shift > 0 and not fz.stop_now


def _agent(tmp_path: Path, steps: list[dict]) -> MockBackend:
    d = tmp_path / "script"
    d.mkdir(exist_ok=True)
    for f in (FIXTURES / "mock").iterdir():
        shutil.copy(f, d / f.name)
    for p in (EXAMPLES / "ne555_blinker" / "reference").glob("*.py"):
        shutil.copy(p, d / p.name)
    (d / "script.yaml").write_text(yaml.safe_dump({"steps": steps}))
    return MockBackend(d)


STEPS = [
    {"role": "designer", "file": "phase1_design.py"},
    {"role": "reviewer", "file": "review.md"},
    {"role": "designer", "file": "hardened_design.py", "spec_issue": "f window tighter than C tolerance"},
]


@needs_ngspice
def test_pipeline_stops_infeasible_then_relaxes_and_passes(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    spec_path = _narrow(proj, 0.97, 1.03)
    cfg = Config()
    cfg.loop.max_iter = 3
    quiet = Console(quiet=True)
    code = Orchestrator(spec_path, cfg, _agent(tmp_path, STEPS), console=quiet).run()
    assert code == EXIT_SPEC_INFEASIBLE
    rd = latest_run(proj)
    st = RunState.load(rd)
    assert st.status == "infeasible" and st.phases["reverify"]["status"] == "infeasible"
    assert len([i for i in st.iterations if i["phase"] == "reverify"]) == 1  # stopped at once
    report = (rd / "spec_infeasible.md").read_text()
    assert "cloop run --relax" in report and "f window tighter than C tolerance" in report
    proposal = json.loads((rd / "relaxation.json").read_text())
    assert {c["field"] for c in proposal["changes"]} == {"min", "max"}

    # too large for the configured limit: reported, spec untouched
    cfg.loop.max_relax = 0.01
    before = spec_path.read_text()
    assert (
        run_with_relaxation(spec_path, cfg, _agent(tmp_path, []), quiet, resume=True) == EXIT_SPEC_INFEASIBLE
    )
    assert spec_path.read_text() == before

    # within the limit: relaxed in place, the same design re-verified, outputs written (no agent call)
    cfg.loop.max_relax = 0.1
    assert run_with_relaxation(spec_path, cfg, _agent(tmp_path, []), quiet, resume=True) == EXIT_OK
    spec = load_spec(spec_path)
    new = {c["field"]: c["new"] for c in proposal["changes"]}
    assert (spec.acceptance[0].min, spec.acceptance[0].max) == (new["min"], new["max"])
    assert any(a.startswith("Relaxed automatically: frequency_OUT 0.97..1.03 ->") for a in spec.assumptions)
    assert list((proj / "spec_history").glob("spec_*.yaml"))
    st2 = RunState.load(latest_run(proj))
    assert st2.status == "passed" and st2.carried_from == str(rd)
    assert (proj / "output" / "final_report.md").is_file()


@needs_ngspice
def test_feasible_window_fails_normally(tmp_path):
    """Off-centre but achievable: not reported as infeasible, the normal fix loop runs out."""
    proj = tmp_path / "proj"
    proj.mkdir()
    spec_path = _narrow(proj, 0.93, 1.27)
    cfg = Config()
    cfg.loop.max_iter = 1
    agent = _agent(tmp_path, STEPS + [{"role": "designer", "file": "hardened_design.py"}])
    assert Orchestrator(spec_path, cfg, agent, console=Console(quiet=True)).run() == EXIT_DESIGN_FAILED
    text = (latest_run(proj) / "failure_report.md").read_text()
    assert "recenter" in text and "Spec issue reported by the design agent" in text
