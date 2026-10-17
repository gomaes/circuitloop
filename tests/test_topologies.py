"""Topology library: deterministic design calculators."""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from circuitloop import EXIT_ENV_ERROR
from circuitloop.cli import app
from circuitloop.partsdb import load_db
from circuitloop.results import Status
from circuitloop.spec import Spec, load_spec
from circuitloop.topologies import TopologyError, applicable, generate
from circuitloop.topologies.eseries import E12, E96, ceil_to, floor_to, fmt_value, nearest

from .conftest import needs_ngspice
from .helpers import EXAMPLES, run_design

CASES = {
    "ldo_5v": "ldo_regulator",
    "ne555_blinker": "ne555_astable",
    "opamp_x10": "noninverting_amp",
    "usb_boost_12v": "mc34063_boost",
}
runner = CliRunner()


def _spec(example: str) -> Spec:
    return load_spec(EXAMPLES / example / "spec.yaml")


def _parts(gen) -> dict[str, tuple[str, str | None]]:
    return {ref: (key, value) for ref, key, value, _ in gen.parts}


def test_eseries():
    assert len(E96) == 96 and E96[:4] == (1.0, 1.02, 1.05, 1.07)
    assert nearest(12.9e3) == 13e3
    assert ceil_to(38.8e-6, (1.0, 1.5, 2.2, 3.3, 4.7, 6.8)) == pytest.approx(47e-6)
    assert floor_to(198, E12) == 180
    assert [fmt_value(x) for x in (0.1, 470e-12, 1.5e3, 1e6)] == ["0.1", "470p", "1.5k", "1M"]


def test_each_example_matches_exactly_one_topology():
    for ex, name in CASES.items():
        fits = [n for n, why in applicable(_spec(ex)) if why is None]
        assert name in fits, (ex, fits)
    assert [n for n, why in applicable(_spec("usb_boost_12v")) if why is None] == ["mc34063_boost"]


def test_boost_sizing_follows_an920():
    gen = generate("mc34063_boost", _spec("usb_boost_12v"), load_db())
    parts = _parts(gen)
    keys = sorted(k for k, _ in parts.values())
    assert keys.count("C_ELEC_25V_D10") == 3  # input bulk + 2 parallel output caps (ESR / 2)
    by_comment = {c: (k, v) for _, k, v, c in gen.parts}
    assert by_comment["boost inductor"] == ("L_POWER_3A", "47u")
    assert ("R_1W", "0.1") in parts.values()  # Rsc = 0.3 V / ~3 A
    assert ("1N5822", None) in parts.values() and ("IRLZ44N", None) in parts.values()
    assert by_comment["gate pull-down: turn-off path"] == ("R_1/4W", "220")
    assert "PTC_RXEF250" in keys  # spec asks for overcurrent protection
    assert any("Ipk = 2 Iout (ratio + 1)" in n for n in gen.notes)
    assert "Design calculations:" in gen.text and gen.text.rstrip().endswith("finish()")


def test_minimal_variant_has_no_protection():
    db = load_db()
    full = {k for k, _ in _parts(generate("ldo_regulator", _spec("ldo_5v"), db)).values()}
    minimal = {k for k, _ in _parts(generate("ldo_regulator", _spec("ldo_5v"), db, protect=False)).values()}
    assert {"PTC_RXEF020", "1N5819"} <= full
    assert not ({"PTC_RXEF020", "1N5819"} & minimal)


def test_555_and_opamp_values():
    db = load_db()
    p = _parts(generate("ne555_astable", _spec("ne555_blinker"), db))
    assert ("C_FILM_100V", "1u") in p.values()  # film timing capacitor
    assert ("R_1/4W", "680k") in p.values()
    p = _parts(generate("noninverting_amp", _spec("opamp_x10"), db))
    assert ("R_1/4W", "18k") in p.values() and ("R_1/4W", "2k") in p.values()  # G = 10 exactly


def test_impossible_spec_explains_why():
    raw = yaml.safe_load((EXAMPLES / "ldo_5v" / "spec.yaml").read_text())
    raw["power_input"].update(v_min=20, v_nom=22, v_max=24)
    raw["loads"] = [{"net": "VOUT", "current": 0.5}]
    raw["faults"] = []
    with pytest.raises(TopologyError, match="dissipation"):
        generate("ldo_regulator", Spec.model_validate(raw), load_db())
    with pytest.raises(TopologyError, match="does not fit"):
        generate("ne555_astable", _spec("ldo_5v"), load_db())
    with pytest.raises(TopologyError, match="unknown parameter"):
        generate("ldo_regulator", _spec("ldo_5v"), load_db(), {"bogus": "1"})


def test_parameter_override():
    gen = generate("ldo_regulator", _spec("ldo_5v"), load_db(), {"regulator": "L7805CV"}, protect=False)
    assert ("L7805CV", None) in _parts(gen).values()


@needs_ngspice
@pytest.mark.parametrize("example", ["ldo_5v", "ne555_blinker", "opamp_x10"])
def test_generated_designs_pass_verification(tmp_path, example):
    """Generated minimal designs pass Phase 2; generated protected designs pass the final gates."""
    db = load_db()
    sp = _spec(example)
    out = run_design(tmp_path / "p1", example, generate(CASES[example], sp, db, protect=False).text)
    assert out.report.passed, out.report.to_markdown()
    out = run_design(tmp_path / "h", example, generate(CASES[example], sp, db).text, phase=3, faults=True)
    assert out.report.passed, out.report.to_markdown()
    assert out.report.gate("G7").status == Status.PASS


def test_cli_topology_commands(tmp_path):
    spec = EXAMPLES / "opamp_x10" / "spec.yaml"
    res = runner.invoke(app, ["topology", "list", "--spec", str(spec)])
    assert res.exit_code == 0 and "noninverting_amp" in res.output
    res = runner.invoke(app, ["topology", "show", "mc34063_boost"])
    assert res.exit_code == 0 and "AN920" in res.output
    out = tmp_path / "design.py"
    res = runner.invoke(
        app, ["topology", "generate", "noninverting_amp", "--spec", str(spec), "-o", str(out)]
    )
    assert res.exit_code == 0, res.output
    assert "finish()" in out.read_text()
    res = runner.invoke(
        app, ["topology", "generate", "ldo_regulator", "--spec", str(spec), "-o", str(tmp_path / "x.py")]
    )
    assert res.exit_code == EXIT_ENV_ERROR  # the op-amp spec has no regulated rail below the input


def test_cli_generate_in_agent_step_only_writes_design_py(tmp_path):
    spec = EXAMPLES / "opamp_x10" / "spec.yaml"
    env = {"CLOOP_AGENT_WORKDIR": str(tmp_path)}
    bad = runner.invoke(
        app,
        ["topology", "generate", "noninverting_amp", "--spec", str(spec), "-o", str(tmp_path / "ref.py")],
        env=env,
    )
    assert bad.exit_code == EXIT_ENV_ERROR and not (tmp_path / "ref.py").exists()
    ok = runner.invoke(
        app,
        ["topology", "generate", "noninverting_amp", "--spec", str(spec), "-o", str(tmp_path / "design.py")],
        env=env,
    )
    assert ok.exit_code == 0
