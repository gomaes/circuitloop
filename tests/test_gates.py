"""Gate tests: reference designs pass, deliberately broken designs are rejected."""

from __future__ import annotations

import pytest

from circuitloop.gates.base import Status

from .conftest import needs_ngspice
from .helpers import reference, rules_hit, run_design

pytestmark = needs_ngspice

LDO_P1 = reference("ldo_5v", "phase1")
NE555_P1 = reference("ne555_blinker", "phase1")
OPAMP_P1 = reference("opamp_x10", "phase1")


@pytest.mark.parametrize("example", ["ldo_5v", "ne555_blinker", "opamp_x10"])
def test_reference_phase1_passes(tmp_path, example):
    out = run_design(tmp_path, example, reference(example, "phase1"))
    assert out.report.passed, out.report.to_markdown()


@pytest.mark.parametrize("example", ["ldo_5v", "ne555_blinker", "opamp_x10"])
def test_reference_hardened_passes_with_faults(tmp_path, example):
    out = run_design(tmp_path, example, reference(example, "hardened"), phase=3, faults=True)
    assert out.report.passed, out.report.to_markdown()


# ---- G1 -------------------------------------------------------------------


def test_g1_syntax_error(tmp_path):
    out = run_design(tmp_path, "ldo_5v", "this is not python\n")
    assert out.report.gate("G1").status == Status.FAIL
    assert out.report.gate("G2").status == Status.SKIPPED
    assert not out.report.passed


def test_g1_missing_finish(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1.replace("finish()", ""))
    assert rules_hit(out, "G1") == {"g1.no_netlist"}


def test_g1_unknown_part(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1.replace('part("LM2940CT-5.0"', 'part("LM9999"'))
    assert rules_hit(out, "G1") == {"g1.exec"}
    assert "not in the parts DB" in out.report.gate("G1").findings[0].message


def test_g1_missing_value(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1.replace('part("C_CER_50V", "470n"', 'part("C_CER_50V"'))
    assert rules_hit(out, "G1") == {"g1.exec"}


# ---- G2 -------------------------------------------------------------------


def test_g2_missing_decoupling(tmp_path):
    code = (
        NE555_P1.replace('u1["RESET"], ra[1], cd[1]', 'u1["RESET"], ra[1]')
        .replace("cc[2], cd[2], d1", "cc[2], d1")
        .replace('cd = part("C_CER_50V", "100n", ref="C3")', "")
    )
    out = run_design(tmp_path, "ne555_blinker", code)
    assert "erc.decoupling" in rules_hit(out, "G2")


def test_g2_ldo_output_cap_too_small(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1.replace('"C_ELEC_16V", "47u"', '"C_ELEC_16V", "4.7u"'))
    assert "erc.decoupling" in rules_hit(out, "G2")


def test_g2_unused_opamp_input_unconnected(tmp_path):
    code = OPAMP_P1.replace(', u1["INPB"]', "")
    out = run_design(tmp_path, "opamp_x10", code)
    assert "erc.unconnected_pin" in rules_hit(out, "G2")


def test_g2_floating_input(tmp_path):
    code = OPAMP_P1.replace(', u1["INPB"]', "").replace(
        'fb_b += u1["OUTB"], u1["INNB"]',
        'fb_b += u1["OUTB"], u1["INNB"]\nfloat_n = Net("FLOAT")\nfloat_n += u1["INPB"], u1["INNA"]',
    )
    out = run_design(tmp_path, "opamp_x10", code.replace(', u1["INNA"]\nfb_b', "\nfb_b"))
    assert "erc.floating_input" in rules_hit(out, "G2")


def test_g2_led_without_resistor(tmp_path):
    code = NE555_P1.replace(
        'out += u1["OUT"], rl[1]\nled_a += rl[2], d1["A"]', 'out += u1["OUT"], d1["A"]'
    ).replace('rl = part("R_1/4W", "470", ref="R3")', "")
    out = run_design(tmp_path, "ne555_blinker", code)
    assert "erc.led_current_limit" in rules_hit(out, "G2")


def test_g2_unregistered_part(tmp_path):
    code = LDO_P1.replace(
        "finish()",
        """
from skidl import Part, Pin, SKIDL
x = Part(tool=SKIDL, name="MYSTERY", ref_prefix="U", footprint="x",
         pins=[Pin(num=1, name="A", func=Pin.types.PASSIVE), Pin(num=2, name="B", func=Pin.types.PASSIVE)])
vin += x[1]
gnd += x[2]
finish()""",
    )
    out = run_design(tmp_path, "ldo_5v", code)
    assert "erc.registered_part" in rules_hit(out, "G2")


def test_g2_required_net_missing(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1.replace('Net("VOUT")', 'Net("V5")'))
    assert "erc.required_nets" in rules_hit(out, "G2")


def test_g2_project_rule_plugin(tmp_path):
    proj = tmp_path / "proj"
    (proj / "rules").mkdir(parents=True)
    (proj / "rules" / "no_ceramic.py").write_text("""
from circuitloop.rules import Finding, Severity, rule

@rule("project.no_ceramic", "ceramic caps are not stocked")
def check(ctx):
    return [Finding("project.no_ceramic", Severity.ERROR, f"{c.ref} is ceramic", refs=[c.ref])
            for c in ctx.netlist.components.values() if c.part_key == "C_CER_50V"]
""")
    from .helpers import EXAMPLES

    out = run_design(
        tmp_path, "ldo_5v", LDO_P1, project_dir=proj, spec_path=EXAMPLES / "ldo_5v" / "spec.yaml"
    )
    assert "project.no_ceramic" in rules_hit(out, "G2")


def test_g2_protection_required_in_phase3(tmp_path):
    out = run_design(tmp_path, "ldo_5v", LDO_P1, phase=3)
    assert "protect.overcurrent" in rules_hit(out, "G2")


# ---- G3 -------------------------------------------------------------------


def test_g3_led_overcurrent(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", NE555_P1.replace('"470", ref="R3"', '"100", ref="R3"'))
    assert "ratings.derating" in rules_hit(out, "G3")
    assert any("D1" in f.refs for f in out.report.gate("G3").findings)


def test_g3_wrong_gain(tmp_path):
    out = run_design(tmp_path, "opamp_x10", OPAMP_P1.replace('"18k", ref="R1"', '"27k", ref="R1"'))
    msgs = [f.message for f in out.report.gate("G3").findings]
    assert any("gain_OUT" in m for m in msgs)


def test_g3_wrong_frequency(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", NE555_P1.replace('"1u", ref="C1"', '"2.2u", ref="C1"'))
    assert any("frequency_OUT" in f.message for f in out.report.gate("G3").findings)


def test_g3_regulator_overloaded(tmp_path):
    code = LDO_P1.replace('part("LM2940CT-5.0", ref="U1")', 'part("L78L05", ref="U1")').replace(
        '"C_CER_50V", "470n"', '"C_CER_50V", "470n"'
    )
    out = run_design(tmp_path, "ldo_5v", code)
    errs = [f for f in out.report.gate("G3").findings if f.rule == "ratings.derating"]
    assert any("U1" in f.refs and "current" in f.message for f in errs)


def test_g3_missing_model_is_incomplete(tmp_path):
    proj = tmp_path / "proj"
    (proj / "parts").mkdir(parents=True)
    (proj / "parts" / "nomodel.yaml").write_text("""
R_NOMODEL:
  description: resistor without a SPICE model
  kind: resistor
  package: axial_400
  footprint: x
  mpn: x
  value: required
  pins: {1: {name: "1"}, 2: {name: "2"}}
  ratings: [{type: power, max: 0.25}]
""")
    code = LDO_P1.replace(
        "finish()", 'rx = part("R_NOMODEL", "10k", ref="R9")\nvout += rx[1]\ngnd += rx[2]\nfinish()'
    )
    from .helpers import EXAMPLES

    out = run_design(tmp_path, "ldo_5v", code, project_dir=proj, spec_path=EXAMPLES / "ldo_5v" / "spec.yaml")
    g3 = out.report.gate("G3")
    assert g3.status == Status.INCOMPLETE
    assert not out.report.passed
    assert any("INCOMPLETE" in u for u in out.report.unverified)


# ---- G5 -------------------------------------------------------------------


def test_g5_reverse_polarity_destroys_unprotected_regulator(tmp_path):
    code = LDO_P1.replace('part("LM2940CT-5.0", ref="U1")', 'part("L7805CV", ref="U1")')
    out = run_design(tmp_path, "ldo_5v", code, faults=True)
    g5 = out.report.gate("G5")
    assert g5.status == Status.FAIL
    assert any("U1" in f.refs and "absolute_max" in f.rule for f in g5.findings)


def test_g5_unprotected_555(tmp_path):
    out = run_design(tmp_path, "ne555_blinker", NE555_P1, faults=True)
    assert out.report.gate("G5").status == Status.FAIL


# ---- G4 -------------------------------------------------------------------


def test_g4_regression_detects_broken_function(tmp_path):
    base = run_design(tmp_path / "a", "opamp_x10", OPAMP_P1)
    assert base.report.passed
    broken = OPAMP_P1.replace('"18k", ref="R1"', '"27k", ref="R1"')
    out = run_design(tmp_path / "b", "opamp_x10", broken, baseline=base.measurements)
    assert out.report.gate("G4").status == Status.FAIL


def test_g4_regression_passes_for_same_design(tmp_path):
    base = run_design(tmp_path / "a", "opamp_x10", OPAMP_P1)
    out = run_design(
        tmp_path / "b", "opamp_x10", reference("opamp_x10", "hardened"), phase=3, baseline=base.measurements
    )
    assert out.report.gate("G4").status == Status.PASS


def test_555_model_never_sticks_midlevel(tmp_path):
    """Regression: the 555 latch must switch cleanly (no analog equilibrium at mid-supply)."""
    import numpy as np

    out = run_design(tmp_path, "ne555_blinker", reference("ne555_blinker", "hardened"))
    for wf in out.sim.waveforms.values():
        t, v = wf.full_tran("OUT")
        mid = (v > 1.0) & (v < v.max() - 0.5)
        assert float(np.sum(np.diff(t)[mid[:-1]])) < 0.01


def test_g2_overcurrent_ptc_after_diode_accepted(tmp_path):
    code = reference("ldo_5v", "hardened").replace(
        'vin += j1[1], f1[1]\nvptc += f1[2], d1["A"]\nvprot += d1["K"],',
        'vin += j1[1], d1["A"]\nvptc += d1["K"], f1[1]\nvprot += f1[2],',
    )
    assert 'd1["K"], f1[1]' in code
    out = run_design(tmp_path, "ldo_5v", code, phase=3)
    assert "protect.overcurrent" not in rules_hit(out, "G2")


def test_g2_overcurrent_ptc_in_shunt_rejected(tmp_path):
    code = reference("ldo_5v", "hardened").replace(
        'vin += j1[1], f1[1]\nvptc += f1[2], d1["A"]', 'vin += j1[1], d1["A"]\nvptc += f1[1]\ngnd += f1[2]'
    )
    out = run_design(tmp_path, "ldo_5v", code, phase=3)
    assert "protect.overcurrent" in rules_hit(out, "G2")
