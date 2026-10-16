from __future__ import annotations

from typer.testing import CliRunner

from circuitloop.cli import app

from .conftest import needs_ngspice
from .helpers import EXAMPLES

runner = CliRunner()


@needs_ngspice
def test_verify_exit_codes(tmp_path):
    spec = EXAMPLES / "opamp_x10" / "spec.yaml"
    good = EXAMPLES / "opamp_x10" / "reference" / "hardened_design.py"
    bad = EXAMPLES / "opamp_x10" / "reference" / "phase1_design.py"
    r = runner.invoke(app, ["verify", str(good), "--spec", str(spec), "--out", str(tmp_path / "a")])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "a" / "report.json").is_file()
    r = runner.invoke(app, ["verify", str(bad), "--spec", str(spec), "--out", str(tmp_path / "b")])
    assert r.exit_code == 1
    r = runner.invoke(
        app, ["verify", str(bad), "--spec", str(spec), "--phase", "design", "--out", str(tmp_path / "c")]
    )
    assert r.exit_code == 0


def test_verify_bad_spec(tmp_path):
    d = tmp_path / "design.py"
    d.write_text("")
    s = tmp_path / "spec.yaml"
    s.write_text("name: x\n")
    r = runner.invoke(app, ["verify", str(d), "--spec", str(s)])
    assert r.exit_code == 2


@needs_ngspice
def test_verify_relative_out_dir(tmp_path, monkeypatch):
    """Regression: agents call `cloop verify design.py --out check` with a relative path."""
    import shutil

    shutil.copy(EXAMPLES / "ldo_5v" / "spec.yaml", tmp_path / "spec.yaml")
    shutil.copy(EXAMPLES / "ldo_5v" / "reference" / "phase1_design.py", tmp_path / "design.py")
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(
        app, ["verify", "design.py", "--spec", "spec.yaml", "--phase", "design", "--quick", "--out", "check"]
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "check" / "build" / "circuit.net").is_file()
