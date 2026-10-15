from __future__ import annotations

import csv

import pytest

from circuitloop.export import export_all
from circuitloop.layout.board import Jumper, build_layout, hole_name, verify_layout
from circuitloop.results import Status

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference, run_design

pytestmark = needs_ngspice


def test_hole_names():
    assert hole_name((0, 0)) == "A1"
    assert hole_name((25, 9)) == "Z10"
    assert hole_name((26, 0)) == "AA1"


@pytest.mark.parametrize("example", ["ldo_5v", "ne555_blinker", "opamp_x10"])
def test_layout_connectivity(tmp_path, example):
    out = run_design(tmp_path, example, reference(example, "hardened"))
    from circuitloop.partsdb import load_db
    from circuitloop.spec import load_spec

    spec = load_spec(EXAMPLES / example / "spec.yaml")
    lay = build_layout(out.netlist, load_db(), spec.board.max_cols, spec.board.max_rows)
    g = verify_layout(lay, out.netlist, spec.board.max_cols, spec.board.max_rows)
    assert g.status == Status.PASS, [f.message for f in g.findings]
    # breaking a trace must be detected as an open net
    if lay.traces:
        lay.traces[0].path = lay.traces[0].path[:1]
        g2 = verify_layout(lay, out.netlist, spec.board.max_cols, spec.board.max_rows)
        assert any(f.rule == "layout.open" for f in g2.findings)


def test_layout_detects_short(tmp_path):
    out = run_design(tmp_path, "ldo_5v", reference("ldo_5v", "hardened"))
    from circuitloop.partsdb import load_db

    lay = build_layout(out.netlist, load_db(), 24, 16)
    a = lay.placed["U1"].pads()[1]  # IN
    b = lay.placed["U1"].pads()[3]  # OUT
    lay.jumpers.append(Jumper("VPROT", a, b))
    g = verify_layout(lay, out.netlist, 24, 16)
    assert any(f.rule == "layout.short" for f in g.findings)


def test_layout_too_small_board(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", reference("ne555_blinker", "hardened"))
    from circuitloop.partsdb import load_db

    lay = build_layout(out.netlist, load_db(), 24, 16)
    g = verify_layout(lay, out.netlist, 8, 8)
    assert any(f.rule == "layout.size" for f in g.findings)


def test_export_all(tmp_path):
    from circuitloop.partsdb import load_db
    from circuitloop.spec import load_spec

    spec = load_spec(EXAMPLES / "opamp_x10" / "spec.yaml")
    out = run_design(tmp_path, "opamp_x10", reference("opamp_x10", "hardened"), phase=3, faults=True)
    design = tmp_path / "design.py"
    res = export_all(design, out, spec, load_db(), tmp_path / "output", tmp_path)
    assert res.ok, [f.message for f in res.findings]
    names = {p.name for p in res.files}
    for f in (
        "opamp_x10.net",
        "schematic.svg",
        "layout_component_side.svg",
        "layout_solder_side.svg",
        "layout.html",
        "bom.csv",
        "build_guide.md",
        "final_report.md",
        "waveform_OUT.png",
    ):
        assert f in names
    rows = list(csv.DictReader((tmp_path / "output" / "bom.csv").open()))
    assert any(r["part"] == "LM358" and r["mpn"] == "LM358P" for r in rows)
    report = (tmp_path / "output" / "final_report.md").read_text()
    assert "G6" in report and "Component stress" in report and "not verified" in report.lower()
