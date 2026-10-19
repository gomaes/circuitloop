"""The new parts work in complete circuits through the real verification (build, ERC, simulation)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from circuitloop.gates import VerifyContext, verify
from circuitloop.partsdb import load_db
from circuitloop.spec import load_spec

from .conftest import needs_ngspice

pytestmark = needs_ngspice


def _verify(tmp_path: Path, spec: dict, design: str, faults: bool = False):
    spec = {"name": "t", "description": "t", "board": {"max_cols": 60, "max_rows": 40}, **spec}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec, sort_keys=False))
    d = tmp_path / "design.py"
    d.write_text("from circuitloop.lib import Net, finish, part\n" + textwrap.dedent(design) + "\nfinish()\n")
    ctx = VerifyContext(load_spec(p), load_db(tmp_path), tmp_path)
    out = verify(d, tmp_path / "work", ctx, phase=3 if faults else 1, faults=faults)
    errors = [f"{g.gate} {f.rule}: {f.message}" for g in out.report.gates for f in g.errors()]
    return out, errors


def _vnom(out, cid):
    return next(v for k, v in out.measurements.items() if k.startswith("vnom"))[cid]


BUCK_SPEC = {
    "power_input": {"pos_net": "VIN", "v_min": 10.0, "v_nom": 12.0, "v_max": 14.4},
    "loads": [{"net": "VOUT", "resistance": 5.0}],  # 1 A: 2 A needs a heatsink (U1 > 1 W derated)
    "transient": {"stop": 8e-3, "step": 50e-9, "settle": 6e-3, "save_step": 0.2e-6, "save_window_only": True},
    "acceptance": [
        {"type": "dc_voltage", "net": "VOUT", "min": 4.75, "max": 5.25},
        {"type": "ripple", "net": "VOUT", "max": 0.1},
    ],
}

BUCK = """
vin, gnd, vout, sw = Net("VIN"), Net("GND"), Net("VOUT"), Net("SW")
j1 = part("TERM_2P_5.08", ref="J1")
j2 = part("TERM_2P_5.08", ref="J2")
u1 = part("LM2596T-5.0", ref="U1")
cin = part("C_ELEC_LESR_25V", "220u", ref="C1")
cbyp = part("C_CER_50V", "100n", ref="C2")
d1 = part("1N5822", ref="D1")
l1 = part("L_RADIAL_12MM", "33u", ref="L1")
cout = part("C_ELEC_LESR_16V", "470u", ref="C3")
vin += j1[1], u1["VIN"], cin["POS"], cbyp[1]
gnd += j1[2], u1["GND"], u1["ON"], cin["NEG"], cbyp[2], d1["A"], cout["NEG"], j2[2]
sw += u1["SW"], d1["K"], l1[1]
vout += l1[2], cout["POS"], u1["FB"], j2[1]
"""


def test_lm2596_buck_regulates(tmp_path):
    out, errors = _verify(tmp_path, BUCK_SPEC, BUCK)
    assert not errors, errors
    v = _vnom(out, "dc_voltage_VOUT")
    assert 4.95 < v < 5.05
    assert _vnom(out, "ripple_VOUT") < 0.05


def test_lm317_sets_output_with_divider(tmp_path):
    spec = {
        "power_input": {"pos_net": "VIN", "v_min": 9.0, "v_nom": 12.0, "v_max": 15.0},
        "loads": [{"net": "VOUT", "current": 0.05}],
        "acceptance": [{"type": "dc_voltage", "net": "VOUT", "min": 4.8, "max": 5.3}],
    }
    design = """
    vin, gnd, vout, adj = Net("VIN"), Net("GND"), Net("VOUT"), Net("ADJ")
    j1 = part("TERM_2P_5.08", ref="J1")
    j2 = part("TERM_2P_5.08", ref="J2")
    u1 = part("LM317T", ref="U1")
    c1 = part("C_CER_50V", "100n", ref="C1")
    c2 = part("C_ELEC_16V", "10u", ref="C2")
    r1 = part("R_1/4W", "240", ref="R1")
    r2 = part("R_1/4W", "715", ref="R2")
    vin += j1[1], u1["IN"], c1[1]
    vout += u1["OUT"], r1[1], c2["POS"], j2[1]
    adj += u1["ADJ"], r1[2], r2[1]
    gnd += j1[2], c1[2], r2[2], c2["NEG"], j2[2]
    """
    out, errors = _verify(tmp_path, spec, design)
    assert not errors, errors
    # 1.25 x (1 + 715/240) + 50 uA x 715 = 5.01 V
    assert _vnom(out, "dc_voltage_VOUT") == pytest.approx(1.25 * (1 + 715 / 240) + 50e-6 * 715, abs=0.03)


def test_pmos_high_side_switch_and_zener(tmp_path):
    """IRF4905 (gate pulled to ground) passes 12 V; a 5.1 V Zener shunt regulates a second rail."""
    spec = {
        "power_input": {"pos_net": "VIN", "v_min": 11.0, "v_nom": 12.0, "v_max": 13.0},
        "loads": [{"net": "VSW", "resistance": 24}, {"net": "VZ", "resistance": 5100}],
        "acceptance": [
            {"type": "dc_voltage", "net": "VSW", "min": 10.9, "max": 13.0},
            {"type": "dc_voltage", "net": "VZ", "min": 4.8, "max": 5.4},
        ],
    }
    design = """
    vin, gnd, vsw, vz, g = Net("VIN"), Net("GND"), Net("VSW"), Net("VZ"), Net("G")
    j1 = part("TERM_2P_5.08", ref="J1")
    j2 = part("HDR_1x03", ref="J2")
    q1 = part("IRF4905", ref="Q1")
    rg = part("R_1/4W", "10k", ref="R1")
    rz = part("R_1/2W", "470", ref="R2")
    dz = part("ZENER_1W", "5.1", ref="D1")
    vin += j1[1], q1["S"], rz[1]
    g += q1["G"], rg[1]
    vsw += q1["D"], j2[1]
    vz += rz[2], dz["K"], j2[2]
    gnd += j1[2], rg[2], dz["A"], j2[3]
    """
    out, errors = _verify(tmp_path, spec, design)
    assert not errors, errors
    assert _vnom(out, "dc_voltage_VSW") > 11.9  # 0.5 A through ~20 mOhm
    assert 4.9 < _vnom(out, "dc_voltage_VZ") < 5.3


def test_tlc555_astable_and_lm393(tmp_path):
    """CMOS 555 blinks at 1/(ln2 (Ra + 2 Rb) C); an LM393 with pull-up follows it."""
    spec = {
        "power_input": {"pos_net": "VIN", "v_min": 4.5, "v_nom": 5.0, "v_max": 5.5},
        "transient": {"stop": 0.03, "step": 2e-6, "settle": 0.01},
        "acceptance": [
            {"type": "frequency", "net": "OUT", "min": 600, "max": 900},
            {"type": "frequency", "net": "CMP", "min": 600, "max": 900},
        ],
    }
    design = """
    vin, gnd, out, thr, dis, ref_, cmp = (Net(n) for n in ("VIN", "GND", "OUT", "THR", "DIS", "REF", "CMP"))
    j1 = part("TERM_2P_5.08", ref="J1")
    j2 = part("HDR_1x03", ref="J2")
    u1 = part("TLC555", ref="U1")
    u2 = part("LM393", ref="U2")
    c1 = part("C_CER_50V", "100n", ref="C1")
    c2 = part("C_CER_50V", "100n", ref="C2")
    ct = part("C_FILM_PET_5PCT", "100n", ref="C3")
    ra = part("R_1/4W", "1k", ref="R1")
    rb = part("R_1/4W", "8.2k", ref="R2")
    r3 = part("R_1/4W", "10k", ref="R3")
    r4 = part("R_1/4W", "10k", ref="R4")
    r5 = part("R_1/4W", "4.7k", ref="R5")
    vin += j1[1], u1["VCC"], u1["RESET"], u2["VCC"], c1[1], c2[1], ra[1], r3[1], r5[1]
    gnd += j1[2], u1["GND"], u2["GND"], c1[2], c2[2], ct[2], r4[2], j2[3], u2["INPB"], u2["INNB"], u2["OUTB"]
    dis += u1["DIS"], ra[2], rb[1]
    thr += u1["THR"], u1["TRIG"], rb[2], ct[1]
    out += u1["OUT"], u2["INNA"], j2[1]
    ref_ += r3[2], r4[1], u2["INPA"]
    cmp += u2["OUTA"], r5[2], j2[2]
    """
    out, errors = _verify(tmp_path, spec, design)
    assert not errors, errors
    f = _vnom(out, "frequency_OUT")
    assert f == pytest.approx(1 / (0.693 * (1e3 + 2 * 8.2e3) * 100e-9), rel=0.12)
    assert _vnom(out, "frequency_CMP") == pytest.approx(f, rel=0.02)
