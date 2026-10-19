"""--agent / --model: the chosen backend and model reach the agent CLI (fake CLIs record their argv)."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from circuitloop.cli import app, parse_agent

from .conftest import needs_ngspice
from .helpers import EXAMPLES

runner = CliRunner()


@pytest.mark.parametrize(
    "agent, model, expected",
    [
        ("opus", None, ("claude", "opus")),
        ("sonnet", None, ("claude", "sonnet")),
        ("haiku", None, ("claude", "haiku")),
        ("claude", None, ("claude", None)),
        ("claude:claude-opus-5-5", None, ("claude", "claude-opus-5-5")),
        ("opencode", None, ("opencode", None)),
        ("opencode:anthropic/claude-sonnet-5-5", None, ("opencode", "anthropic/claude-sonnet-5-5")),
        ("claude", "sonnet", ("claude", "sonnet")),
        (None, "haiku", (None, "haiku")),
    ],
)
def test_parse_agent(agent, model, expected):
    assert parse_agent(agent, model) == expected


@pytest.mark.parametrize("agent, model", [("gpt", None), ("opus", "haiku"), ("opencode:x", "y")])
def test_parse_agent_rejects(agent, model):
    with pytest.raises(ValueError):
        parse_agent(agent, model)


FAKE = """#!/bin/sh
echo "$0 $*" >> "$FAKE_ARGS"
if [ -n "$FAKE_SPEC" ] && [ ! -f spec.yaml ]; then cp "$FAKE_SPEC" spec.yaml; fi
echo '{"result": "done", "is_error": false, "total_cost_usd": 0}'
"""


@pytest.fixture
def fake_clis(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("claude", "opencode"):
        p = bindir / name
        p.write_text(FAKE)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "args.txt"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ARGS", str(log))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # no user config
    return log


def _project(tmp_path: Path, toml: str = "") -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(EXAMPLES / "opamp_x10" / "spec.yaml", proj / "spec.yaml")
    (proj / "cloop.toml").write_text(toml)
    return proj


@needs_ngspice
@pytest.mark.parametrize(
    "args, expect",
    [
        (["--agent", "opus"], ["/claude ", "--model opus"]),
        (["-a", "haiku"], ["/claude ", "--model haiku"]),
        (["--agent", "claude", "--model", "sonnet"], ["/claude ", "--model sonnet"]),
        (
            ["--agent", "opencode:anthropic/claude-sonnet-5-5"],
            ["/opencode ", "-m anthropic/claude-sonnet-5-5"],
        ),
    ],
)
def test_run_passes_backend_and_model(tmp_path, fake_clis, args, expect):
    proj = _project(tmp_path)
    r = runner.invoke(app, ["run", str(proj / "spec.yaml"), "--max-iter", "1", *args])
    assert r.exit_code == 1, r.output  # the fake agent writes no design: fails, but was called
    calls = fake_clis.read_text().splitlines()
    assert calls and all(all(e in c for e in expect) for c in calls), calls


@needs_ngspice
def test_switching_backend_drops_the_configured_model(tmp_path, fake_clis):
    proj = _project(tmp_path, '[agent]\nbackend = "claude"\nmodel = "haiku"\n')
    r = runner.invoke(app, ["run", str(proj / "spec.yaml"), "--max-iter", "1", "--agent", "opencode"])
    assert r.exit_code == 1, r.output
    calls = fake_clis.read_text().splitlines()
    assert calls and all("/opencode " in c and " -m " not in c for c in calls), calls


def test_new_records_the_chosen_model(tmp_path, fake_clis, monkeypatch):
    monkeypatch.setenv("FAKE_SPEC", str(EXAMPLES / "opamp_x10" / "spec.yaml"))
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["new", "x10 amplifier", "--agent", "sonnet", "--no-run"])
    assert r.exit_code == 0, r.output
    assert "--model sonnet" in fake_clis.read_text()
    toml = next(tmp_path.glob("*/cloop.toml")).read_text()
    assert 'backend = "claude"' in toml and 'model = "sonnet"' in toml


def test_bad_agent_is_an_environment_error(tmp_path):
    r = runner.invoke(app, ["run", str(EXAMPLES / "ldo_5v" / "spec.yaml"), "--agent", "gpt"])
    assert r.exit_code == 2 and "--agent must be" in r.output
