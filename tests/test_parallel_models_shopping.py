"""Parallel simulation, quick self-check, external vendor models, shopping list."""

from __future__ import annotations

import textwrap

from circuitloop.export.shopping import shopping_items
from circuitloop.gates import VerifyContext, verify
from circuitloop.partsdb import load_db
from circuitloop.results import Status
from circuitloop.sim.pool import auto_jobs, available_cpus
from circuitloop.spec import load_spec

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference, run_design


def test_auto_jobs_bounds():
    assert auto_jobs(1) == 1
    assert 1 <= auto_jobs(10) <= max(1, available_cpus())
    assert auto_jobs(4, requested=2) == 2
    assert auto_jobs(2, requested=8) == 2


@needs_ngspice
def test_parallel_equals_sequential(tmp_path):
    spec = load_spec(EXAMPLES / "ne555_blinker" / "spec.yaml")
    design = tmp_path / "design.py"
    design.write_text(reference("ne555_blinker", "hardened"))
    db = load_db()
    res = {}
    for jobs in (1, 4):
        ctx = VerifyContext(spec, db, EXAMPLES / "ne555_blinker", sim_jobs=jobs)
        out = verify(design, tmp_path / f"w{jobs}", ctx, phase=3, faults=True)
        assert out.report.passed
        res[jobs] = out
    assert res[1].measurements == res[4].measurements
    assert res[4].sim.result.metrics["parallel_jobs"] == min(4, 4)


@needs_ngspice
def test_quick_mode(tmp_path):
    spec = load_spec(EXAMPLES / "ldo_5v" / "spec.yaml")
    design = tmp_path / "design.py"
    design.write_text(reference("ldo_5v", "hardened"))
    ctx = VerifyContext(spec, load_db(), EXAMPLES / "ldo_5v")
    out = verify(design, tmp_path / "w", ctx, phase=3, faults=True, baseline={"x": {}}, quick=True)
    assert list(out.measurements) == ["vnom=9V"]
    assert [g.gate for g in out.report.gates] == ["G1", "G2", "G3"]
    assert any("quick" in u for u in out.report.unverified)


VENDOR_LIB = """\
* vendor-style model file (PSpice syntax)
.SUBCKT VENDOR_RES 1 2 PARAMS: R=1k
R1 1 2 {R}
.ENDS VENDOR_RES
"""


def _vendor_project(tmp_path, with_file: bool):
    proj = tmp_path / "proj"
    (proj / "parts" / "models").mkdir(parents=True)
    if with_file:
        (proj / "parts" / "models" / "vendor.lib").write_text(VENDOR_LIB)
    (proj / "parts" / "vendor.yaml").write_text(
        textwrap.dedent("""
        R_VENDOR:
          description: resistor with a vendor subcircuit model
          kind: resistor
          package: axial_400
          footprint: x
          mpn: VENDOR-R
          value: required
          pins: {1: {name: "1"}, 2: {name: "2"}}
          ratings: [{type: power, max: 0.25}]
          spice:
            type: subckt
            line: "X{ref} {1} {2} VENDOR_RES PARAMS: R={value}"
            include: models/vendor.lib
            compat: ps
    """)
    )
    return proj


@needs_ngspice
def test_vendor_model_include_and_compat(tmp_path):
    proj = _vendor_project(tmp_path, with_file=True)
    db = load_db(proj)
    assert db["R_VENDOR"].spice.include == str(proj / "parts" / "models" / "vendor.lib")
    assert db.model_files() == [proj / "parts" / "models" / "vendor.lib"]
    code = reference("ldo_5v", "phase1").replace(
        "finish()", 'rx = part("R_VENDOR", "10k", ref="R9")\nvout += rx[1]\ngnd += rx[2]\nfinish()'
    )
    out = run_design(
        tmp_path / "a", "ldo_5v", code, project_dir=proj, spec_path=EXAMPLES / "ldo_5v" / "spec.yaml"
    )
    assert out.report.gate("G3").status == Status.PASS, out.report.to_markdown()
    simdir = tmp_path / "a" / "work" / "sim" / "vnom"
    assert (simdir / ".spiceinit").read_text().strip() == "set ngbehavior=ps"
    assert '.include "' in (simdir / "deck.cir").read_text()


@needs_ngspice
def test_vendor_model_file_missing_is_incomplete(tmp_path):
    proj = _vendor_project(tmp_path, with_file=False)
    code = reference("ldo_5v", "phase1").replace(
        "finish()", 'rx = part("R_VENDOR", "10k", ref="R9")\nvout += rx[1]\ngnd += rx[2]\nfinish()'
    )
    out = run_design(
        tmp_path / "b", "ldo_5v", code, project_dir=proj, spec_path=EXAMPLES / "ldo_5v" / "spec.yaml"
    )
    assert out.report.gate("G3").status == Status.INCOMPLETE
    assert not out.report.passed


@needs_ngspice
def test_shopping_list(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", reference("ne555_blinker", "hardened"))
    layout = {
        "cols": 12,
        "rows": 10,
        "traces": [{"net": "A", "path": [[0, 0], [0, 1], [0, 2]]}],
        "jumpers": [{"net": "B", "a": [0, 0], "b": [3, 4]}],
    }
    items = shopping_items(out.netlist, load_db(), layout, boards=3, spares=0.1)
    by = {(i.name, i.value): i for i in items}
    assert by[("NE555", "")].qty == 3
    assert by[("R_1/4W", "100k")].qty == 3 + 1  # +10 %, at least one spare
    assert by[("DIP-8 IC socket", "")].qty == 3
    assert any(i.category == "board" and i.value == "12x10 holes" for i in items)
    assert any(i.category == "wire" and i.unit == "m" for i in items)
