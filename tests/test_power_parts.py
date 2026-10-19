"""Switching-converter support: rating modes, input_current, windowed transient, boost example."""

from __future__ import annotations

import numpy as np
import pytest

from circuitloop.partsdb import Rating, load_db
from circuitloop.sim.measure import _check_one
from circuitloop.sim.spice import Scenario, build_deck
from circuitloop.spec import load_spec

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference, rules_hit, run_design


class _WF:
    """Minimal Waveforms stand-in: a square current 0/2 A with 50 % duty."""

    def __init__(self):
        self.t = np.linspace(0, 1, 1001)
        self.x = np.where((self.t * 10) % 1 < 0.5, 2.0, 0.0)

    def i(self, name):
        return self.x

    def mean(self, x):
        return float(np.trapezoid(x, self.t) / (self.t[-1] - self.t[0]))


@pytest.mark.parametrize(
    "mode, limit, passed",
    [
        ("peak", 1.9, False),
        ("peak", 2.1, True),
        ("average", 1.1, True),
        ("average", 0.9, False),
        ("rms", 1.5, True),
        ("rms", 1.3, False),
    ],
)
def test_current_rating_modes(mode, limit, passed):
    pd = load_db()["1N5822"]
    r = Rating(type="current", pin=1, max=limit, mode=mode)
    rc = _check_one("D1", pd, r, _WF(), {"current": 1.0})
    assert rc.passed is passed


def test_windowed_transient_deck():
    spec = load_spec(EXAMPLES / "usb_boost_12v" / "spec.yaml")
    nl_spec = spec.transient
    assert nl_spec.save_window_only and nl_spec.save_step
    from circuitloop.netlist import Netlist

    deck = build_deck(Netlist({}, {}), load_db(), spec, Scenario("x", 5.0)).text
    assert "set interp" in deck
    assert "tran 5e-07 0.03 0.025 2e-07 uic" in deck


def test_new_parts_present():
    db = load_db()
    for key in ("MC34063", "IRLZ44N", "1N5822", "L_POWER_3A", "C_ELEC_25V_D10", "R_1W", "PTC_RXEF250"):
        assert key in db and db[key].spice is not None
    assert db["L_POWER_3A"].kind == "inductor"


@needs_ngspice
def test_boost_reference_passes(tmp_path):
    out = run_design(tmp_path, "usb_boost_12v", reference("usb_boost_12v", "hardened"), phase=3, faults=True)
    assert out.report.passed, out.report.to_markdown()
    for vals in out.measurements.values():
        assert 11.4 <= vals["dc_voltage_VOUT"] <= 12.6
        assert vals["input_current"] <= 2.2


@needs_ngspice
def test_boost_without_current_limit_resistor_rated(tmp_path):
    """A 1/4 W sense resistor is overstressed (average power) and must be rejected."""
    code = reference("usb_boost_12v", "hardened").replace('part("R_1W", "0.1"', 'part("R_1/4W", "0.1"')
    out = run_design(tmp_path, "usb_boost_12v", code)
    assert any("R1" in f.refs for f in out.report.gate("G3").errors())
    assert "ratings.derating" in rules_hit(out, "G3")


def test_value_range_enforced():
    from circuitloop.partsdb import check_value

    db = load_db()
    assert "above the range" in check_value(db["C_ELEC_16V"], "10m")
    assert check_value(db["C_ELEC_16V"], "470u") is None  # larger can (sizes)
    assert "below the range" in check_value(db["C_ELEC_25V_D10"], "10u")
    assert check_value(db["C_ELEC_25V_D10"], "1000u") is None
