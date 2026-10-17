"""Deterministic diagnosis of failed verifications."""

from __future__ import annotations

from circuitloop.diagnose import Circuit, mc34063
from circuitloop.netlist import read_netlist
from circuitloop.partsdb import load_db
from circuitloop.report import VerificationReport
from circuitloop.spec import load_spec

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference, run_design


def _topics(out) -> dict[str, dict]:
    return {d["topic"]: d for d in out.report.diagnosis}


@needs_ngspice
def test_passing_design_has_no_diagnosis(tmp_path):
    out = run_design(tmp_path, "opamp_x10", reference("opamp_x10", "phase1"))
    assert out.report.passed and out.report.diagnosis == []


@needs_ngspice
def test_555_frequency_names_the_resistor_and_value(tmp_path):
    code = reference("ne555_blinker", "phase1").replace('"680k", ref="R2"', '"330k", ref="R2"')
    out = run_design(tmp_path, "ne555_blinker", code)
    assert not out.report.passed
    d = _topics(out)["ne555.frequency"]
    assert "1.9" in d["cause"] or "2" in d["cause"]  # 1/(0.693 x 760k x 1u) = 1.9 Hz
    assert "R2" in d["fix"] and "680k" in d["fix"]
    assert "Diagnosis" in out.report.to_markdown()


@needs_ngspice
def test_555_tolerance_failure_points_at_the_capacitor(tmp_path):
    code = (
        reference("ne555_blinker", "hardened")
        .replace('ra = part("R_1/4W", "100k", ref="R1")', 'ra = part("R_1/4W", "10k", ref="R1")')
        .replace('rb = part("R_1/4W", "680k", ref="R2")', 'rb = part("R_1/4W", "68k", ref="R2")')
        .replace('ct = part("C_FILM_100V", "1u", ref="C1")', 'ct = part("C_ELEC_16V", "10u", ref="C1")')
        .replace("ct[2]", 'ct["NEG"]')
        .replace("ct[1]", 'ct["POS"]')
    )
    out = run_design(tmp_path, "ne555_blinker", code, phase=3, faults=True)
    assert "film" in _topics(out)["ne555.tolerance"]["fix"]


@needs_ngspice
def test_opamp_gain(tmp_path):
    code = reference("opamp_x10", "phase1").replace('"18k", ref="R1"', '"27k", ref="R1"')
    out = run_design(tmp_path, "opamp_x10", code)
    d = _topics(out)["opamp.gain"]
    assert "14.5" in d["cause"] and "18k" in d["fix"]


@needs_ngspice
def test_regulator_dropout_and_series_drop(tmp_path):
    code = reference("ldo_5v", "hardened").replace("LM2940CT-5.0", "L7805CV")
    out = run_design(tmp_path, "ldo_5v", code)
    topics = _topics(out)
    assert "regulator.dropout" in topics
    assert "D1 Vf ~0.9" in topics["regulator.dropout"]["cause"]  # 1N4007 in the input path
    assert "Schottky" in topics["regulator.dropout"]["fix"]


def _boost_circuit(tmp_path, code: str) -> Circuit:
    """Static (netlist-only) diagnosis of a boost design."""
    from circuitloop.gates.g1_build import run_g1

    spec = load_spec(EXAMPLES / "usb_boost_12v" / "spec.yaml")
    design = tmp_path / "design.py"
    design.write_text(code)
    g1 = run_g1(design, tmp_path / "build", spec, EXAMPLES / "usb_boost_12v")
    assert g1.result.passed, g1.result.findings
    rep = VerificationReport(design=str(design), phase="test")
    return Circuit(read_netlist(g1.netlist_path), load_db(), spec, rep)


def test_boost_missing_gate_pulldown(tmp_path):
    code = reference("usb_boost_12v", "hardened")
    code = code.replace('rpd = part("R_1/4W", "220", ref="R3")  # gate pull-down (turn-off path)\n', "")
    code = code.replace('gate += rg[2], q1["G"], rpd[1]', 'gate += rg[2], q1["G"]').replace(" rpd[2],", "")
    topics = {d.topic: d for d in mc34063(_boost_circuit(tmp_path, code))}
    assert "mc34063.gate_pulldown" in topics
    assert "emitter follower" in topics["mc34063.gate_pulldown"].cause


def test_boost_slow_turn_off_and_setpoint(tmp_path):
    code = (
        reference("usb_boost_12v", "hardened")
        .replace('"220", ref="R3"', '"4.7k", ref="R3"')
        .replace('"13k", ref="R4"', '"15k", ref="R4"')
    )
    topics = {d.topic: d for d in mc34063(_boost_circuit(tmp_path, code))}
    assert "mc34063.gate_turnoff" in topics  # 4.7k x 1.7 nF = 8 us >> toff ~1.7 us
    sp = topics["mc34063.setpoint"]
    assert "13.8" in sp.cause and "R4" in sp.fix


def test_reference_boost_is_clean(tmp_path):
    assert mc34063(_boost_circuit(tmp_path, reference("usb_boost_12v", "hardened"))) == []
