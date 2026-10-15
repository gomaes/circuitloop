from __future__ import annotations

import pytest

from circuitloop.resources import template_path
from circuitloop.spec import SpecError, load_spec


def _write(tmp_path, text):
    p = tmp_path / "spec.yaml"
    p.write_text(text)
    return p


BASE = """
name: t
description: test
power_input: {v_min: 8, v_nom: 9, v_max: 12, pos_net: VIN}
acceptance:
  - {type: dc_voltage, net: VOUT, min: 4.8, max: 5.2}
"""


def test_template_is_valid():
    spec = load_spec(template_path("spec.yaml"))
    assert spec.power_input.v_nom == 9.0
    assert "VOUT" in spec.required_nets()


def test_minimal_spec(tmp_path):
    spec = load_spec(_write(tmp_path, BASE))
    assert spec.acceptance[0].key() == "dc_voltage_VOUT"
    assert spec.power_input.corners() == {"vmin": 8, "vnom": 9, "vmax": 12}


def test_corners_dedup(tmp_path):
    spec = load_spec(
        _write(tmp_path, BASE.replace("v_min: 8, v_nom: 9, v_max: 12", "v_min: 5, v_nom: 5, v_max: 5"))
    )
    assert spec.power_input.corners() == {"vmin": 5}


@pytest.mark.parametrize(
    "mutation, msg",
    [
        (("v_min: 8", "v_min: 10"), "v_min <= v_nom"),
        (("type: dc_voltage", "type: frequency"), "transient"),
        (("name: t", "name: 'bad name'"), "name"),
        (("description: test\n", "description: test\nunknown_key: 1\n"), "unknown_key"),
    ],
)
def test_invalid_specs(tmp_path, mutation, msg):
    with pytest.raises(SpecError, match=msg):
        load_spec(_write(tmp_path, BASE.replace(*mutation)))


def test_missing_file(tmp_path):
    with pytest.raises(SpecError, match="not found"):
        load_spec(tmp_path / "nope.yaml")


def test_auto_reverse_fault(tmp_path):
    spec = load_spec(_write(tmp_path, BASE + "protection: [reverse_polarity]\n"))
    assert [f.kind for f in spec.effective_faults()] == ["reverse_polarity"]
