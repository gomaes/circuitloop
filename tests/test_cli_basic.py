from __future__ import annotations

import pytest
from typer.testing import CliRunner

from circuitloop.cli import app
from circuitloop.doctor import distro_family, install_hint
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
    assert distro_family(tmp_path / "missing", probe=False) == "unknown"


@pytest.mark.parametrize(
    "release",
    [
        'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n',
        'NAME="Manjaro Linux"\nID="manjaro"\nID_LIKE="arch"\n',
        'NAME="EndeavourOS"\nID="endeavouros"\nID_LIKE="arch"\n',
        'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n',
        'NAME="Arch Linux ARM"\nID=archarm\nID_LIKE=arch\n',
    ],
)
def test_arch_family(tmp_path, release):
    p = tmp_path / "os-release"
    p.write_text(release)
    assert distro_family(p, probe=False) == "pacman"


def test_no_false_arch_match(tmp_path):
    p = tmp_path / "os-release"
    p.write_text("ID=research-os\n")
    assert distro_family(p, probe=False) == "unknown"


def test_install_hints():
    assert install_hint("ngspice", "pacman") == "sudo pacman -S --needed ngspice"
    assert install_hint("npm", "pacman") == "sudo pacman -S --needed nodejs npm"
    assert install_hint("ngspice", "apt") == "sudo apt install ngspice"
    assert "ngspice.sourceforge.io" in install_hint("ngspice", "unknown")


def test_doctor_runs():
    r = runner.invoke(app, ["doctor", "--agent", "claude"])
    assert r.exit_code in (0, 2)
    assert "ngspice" in r.stdout


def test_parts_list():
    r = runner.invoke(app, ["parts", "list", "--kind", "opamp"])
    assert r.exit_code == 0 and "LM358" in r.stdout


def test_parts_add(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "new.yaml"
    f.write_text("""
R_2W:
  description: 2 W resistor
  kind: resistor
  package: axial_500
  footprint: x
  mpn: "2W {value}"
  value: required
  pins: {1: {name: "1"}, 2: {name: "2"}}
  ratings: [{type: power, max: 2.0}]
  spice: {type: primitive, line: "R{ref} {1} {2} {value}"}
""")
    r = runner.invoke(app, ["parts", "add", str(f)])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "parts" / "local.yaml").is_file()
    r = runner.invoke(app, ["parts", "add", str(f)])
    assert r.exit_code == 2  # already registered
    bad = tmp_path / "bad.yaml"
    bad.write_text("X: {description: d}\n")
    assert runner.invoke(app, ["parts", "add", str(bad)]).exit_code == 2
