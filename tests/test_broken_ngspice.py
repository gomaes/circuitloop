"""A broken ngspice installation is an environment error (exit 2), never a design failure."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from circuitloop import EXIT_ENV_ERROR
from circuitloop.agents.mock import MockBackend
from circuitloop.cli import app
from circuitloop.config import Config
from circuitloop.doctor import broken_hint
from circuitloop.orchestrator import Orchestrator
from circuitloop.sim.ngspice import NgspiceUnavailable, run_ngspice, smoke_test

from .helpers import EXAMPLES, reference

runner = CliRunner()
GLIBC = "/usr/bin/ngspice: /usr/lib/libm.so.6: version `GLIBC_2.44' not found (required by /usr/bin/ngspice)"


@pytest.fixture
def broken_ngspice(tmp_path, monkeypatch) -> Path:
    """An `ngspice` on PATH that fails like a partially upgraded Arch system."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "ngspice"
    exe.write_text(f"#!/bin/sh\ncat >&2 <<'MSG'\n{GLIBC}\nMSG\nexit 1\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    assert shutil.which("ngspice") == str(exe)
    return exe


def test_detected_as_unavailable(broken_ngspice, tmp_path):
    assert "GLIBC_2.44" in smoke_test()
    with pytest.raises(NgspiceUnavailable, match="cannot run on this system"):
        run_ngspice("* x\n.end\n", tmp_path / "w")


def test_doctor_explains_the_partial_upgrade():
    assert "pacman -Syu" in broken_hint(GLIBC, "pacman")
    assert "reinstall" in broken_hint(GLIBC, "apt")


def test_verify_exits_with_environment_error(broken_ngspice, tmp_path):
    design = tmp_path / "design.py"
    design.write_text(reference("opamp_x10", "phase1"))
    res = runner.invoke(
        app,
        ["verify", str(design), "--spec", str(EXAMPLES / "opamp_x10" / "spec.yaml"), "--phase", "design"],
    )
    assert res.exit_code == EXIT_ENV_ERROR
    assert "not a" in res.output and "GLIBC_2.44" in res.output


def test_pipeline_stops_before_calling_the_agent(broken_ngspice, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(EXAMPLES / "opamp_x10" / "spec.yaml", proj / "spec.yaml")
    script = tmp_path / "script"
    script.mkdir()
    (script / "script.yaml").write_text("steps: []\n")
    agent = MockBackend(script)
    code = Orchestrator(proj / "spec.yaml", Config(), agent, console=Console(quiet=True)).run()
    assert code == EXIT_ENV_ERROR and agent.calls == 0
