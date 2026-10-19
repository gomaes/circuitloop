"""Every registered part: its SPICE model parses and simulates in ngspice, and its data is consistent."""

from __future__ import annotations

import math
import re

import pytest

from circuitloop.layout.packages import PACKAGES
from circuitloop.netlist import Component, Netlist
from circuitloop.partsdb import load_db
from circuitloop.sim.ngspice import run_ngspice
from circuitloop.sim.spice import Scenario, build_deck
from circuitloop.spec import Spec
from circuitloop.units import parse_value

from .conftest import needs_ngspice

DB = load_db()
DEFAULT = {
    "resistor": 1e3,
    "capacitor": 100e-9,
    "electrolytic": 10e-6,
    "inductor": 100e-6,
    "zener": 5.1,
    "tvs": 15,
}


def _values(pd) -> list[float]:
    """A mid-range value plus one per size (so every can / body of a family is exercised)."""
    if pd.value != "required":
        return []
    lo, hi = pd.value_min, pd.value_max
    v = DEFAULT.get(pd.kind, 1.0)
    if lo is not None and hi is not None:
        v = math.sqrt(lo * hi)
    elif lo is not None:
        v = max(v, lo)
    elif hi is not None:
        v = min(v, hi)
    return sorted({v, *(z.value_max for z in pd.sizes)})


SPEC = Spec.model_validate(
    {
        "name": "model_check",
        "description": "model check",
        "power_input": {"pos_net": "VIN", "v_min": 5, "v_nom": 5, "v_max": 5},
        "transient": {"stop": 20e-6, "step": 50e-9},
        "acceptance": [{"type": "input_power", "max": 100}],
    }
)


@needs_ngspice
@pytest.mark.parametrize("key", [k for k in DB.keys() if DB[k].spice and DB[k].spice.type != "connector"])
def test_model_simulates(tmp_path, key):
    pd = DB[key]
    for value in _values(pd) or [None]:
        val = None if value is None else f"{value:.6g}"
        nets: dict[str, list[tuple[str, str]]] = {}
        for i, num in enumerate(sorted(pd.pins)):
            net = "VIN" if i == 0 else "GND" if i == 1 else f"N{num}"
            nets.setdefault(net, []).append(("X1", str(num)))
        nl = Netlist({"X1": Component("X1", val or key, "", key)}, nets)
        deck = build_deck(nl, DB, SPEC, Scenario("check", 5.0))
        assert deck.simulated == ["X1"], deck.missing_model
        res = run_ngspice(deck.text, tmp_path / f"{key.replace('/', '_')}_{val}", timeout=60)
        log = (tmp_path / f"{key.replace('/', '_')}_{val}" / "ngspice.log").read_text()
        bad = [ln for ln in log.splitlines() if re.search(r"error|unknown|no such|undefined", ln, re.I)]
        assert not bad, f"{key} {val}: {bad[:3]}"
        assert res.tran_error is None, f"{key} {val}: {res.tran_error}"


@pytest.mark.parametrize("key", DB.keys())
def test_part_data_consistent(key):
    pd = DB[key]
    for z in pd.sizes or [None]:
        p = pd if z is None else pd.for_value(z.value_max)
        assert p.package in PACKAGES, f"{key}: unknown package {p.package}"
        pads = PACKAGES[p.package].pads
        assert set(pads) == set(p.pins), (
            f"{key}: package {p.package} pads {sorted(pads)} vs pins {sorted(p.pins)}"
        )
        assert p.footprint.count(":") == 1, f"{key}: footprint must be Library:Name"
    if pd.value == "required" and pd.value_min and pd.value_max:
        assert pd.value_min < pd.value_max
    if pd.mpn and "{value}" not in pd.mpn and pd.value == "required":
        pytest.fail(f"{key}: value-required part needs {{value}} in its mpn")
    for d in pd.decoupling:
        assert d.pin in pd.pins and d.gnd in pd.pins


def test_value_dependent_body_and_ratings():
    pd = DB["C_ELEC_25V"]
    small, big = DB.resolve("C_ELEC_25V", "10u"), DB.resolve("C_ELEC_25V", "1000u")
    assert small.package == "ecap_d5" and big.package == "ecap_d16"
    assert big.design["esr"] < small.design["esr"]
    rms = [r.max for r in big.ratings if r.type == "current"]
    assert rms and rms[0] > [r.max for r in small.ratings if r.type == "current"][0]
    assert any(r.type == "voltage" and r.max == 25 for r in big.ratings)  # kept from the family
    assert pd.value_max == pytest.approx(parse_value("2200u"))
