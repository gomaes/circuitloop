from __future__ import annotations

from typer.testing import CliRunner

from circuitloop.cli import app
from circuitloop.doctor import distro_family
from circuitloop.spec import load_spec

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0 and "circuitloop" in r.stdout


def test_init_creates_project(tmp_path):
    d = tmp_path / "proj"
    r = runner.invoke(app, ["init", str(d)])
    assert r.exit_code == 0, r.output
    assert (d / "cloop.toml").is_file()
    assert load_spec(d / "spec.yaml").name == "proj"


def test_init_refuses_nonempty(tmp_path):
    (tmp_path / "x").write_text("x")
    r = runner.invoke(app, ["init", str(tmp_path)])
    assert r.exit_code == 2


def test_distro_family(tmp_path):
    p = tmp_path / "os-release"
    p.write_text("ID=ubuntu\nID_LIKE=debian\n")
    assert distro_family(p) == "apt"
    p.write_text('ID="fedora"\n')
    assert distro_family(p) == "dnf"
    p.write_text("ID=arch\n")
    assert distro_family(p) == "pacman"
    assert distro_family(tmp_path / "missing") == "unknown"


def test_doctor_runs():
    r = runner.invoke(app, ["doctor", "--agent", "claude"])
    assert r.exit_code in (0, 2)
    assert "ngspice" in r.stdout
