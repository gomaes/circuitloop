"""G7 tolerance analysis."""

from __future__ import annotations

import yaml

from circuitloop.gates.g7_tolerance import tolerance_items
from circuitloop.partsdb import load_db
from circuitloop.results import Status

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference, run_design


def _gate(out, name="G7"):
    return out.report.gate(name)


@needs_ngspice
def test_items_include_values_and_model_parameters(tmp_path):
    out = run_design(tmp_path, "ldo_5v", reference("ldo_5v", "hardened"))
    items = tolerance_items(out.netlist, load_db())
    assert ("U1", "vout", 0.03) in items  # regulator output tolerance (model parameter)
    assert ("C1", "value", 0.10) in items  # X7R ceramic


@needs_ngspice
def test_electrolytic_timing_cap_fails_tolerance(tmp_path):
    """A 555 timed by a +/-20 % electrolytic cannot hold +/-15 % frequency."""
    code = (
        reference("ne555_blinker", "hardened")
        .replace('ra = part("R_1/4W", "100k", ref="R1")', 'ra = part("R_1/4W", "10k", ref="R1")')
        .replace('rb = part("R_1/4W", "680k", ref="R2")', 'rb = part("R_1/4W", "68k", ref="R2")')
        .replace('ct = part("C_FILM_100V", "1u", ref="C1")', 'ct = part("C_ELEC_16V", "10u", ref="C1")')
        .replace("ct[2]", 'ct["NEG"]')
        .replace("ct[1]", 'ct["POS"]')
    )
    out = run_design(tmp_path, "ne555_blinker", code, phase=3, faults=True)
    assert out.report.gate("G3").status == Status.PASS  # nominal design is fine ...
    g7 = _gate(out)
    assert g7.status == Status.FAIL  # ... but not with real parts
    assert any("frequency_OUT" in f.message and "C1" in f.message for f in g7.errors())


@needs_ngspice
def test_film_timing_cap_passes_tolerance(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", reference("ne555_blinker", "hardened"), phase=3, faults=True)
    assert _gate(out).status == Status.PASS
    rows = {r["id"]: r for r in _gate(out).metrics["criteria"]}
    lo, hi = (float(x) for x in rows["frequency_OUT"]["value"].split(" .. "))
    assert 0.85 <= lo < hi <= 1.15


@needs_ngspice
def test_monte_carlo_and_disable(tmp_path):
    spec = yaml.safe_load((EXAMPLES / "opamp_x10" / "spec.yaml").read_text())
    spec["tolerance"] = {"method": "monte_carlo", "samples": 6, "seed": 3}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    out = run_design(
        tmp_path / "a", "opamp_x10", reference("opamp_x10", "hardened"), phase=3, faults=True, spec_path=p
    )
    g7 = _gate(out)
    assert g7.status == Status.PASS and g7.metrics["method"] == "monte_carlo"
    assert any("6 samples, 6 passed" in n for n in g7.notes)
    spec["tolerance"] = {"enabled": False}
    p.write_text(yaml.safe_dump(spec))
    out = run_design(
        tmp_path / "b", "opamp_x10", reference("opamp_x10", "hardened"), phase=3, faults=True, spec_path=p
    )
    assert _gate(out).status == Status.PASS and "disabled" in _gate(out).notes[0]
