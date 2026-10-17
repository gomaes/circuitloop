"""`cloop new`: specification written by the agent from a short request, checked deterministically."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from circuitloop import EXIT_DESIGN_FAILED, EXIT_ENV_ERROR, EXIT_OK
from circuitloop.agents.base import AgentTask
from circuitloop.agents.claude import ClaudeBackend
from circuitloop.agents.mock import MockBackend
from circuitloop.cli import app
from circuitloop.partsdb import load_db
from circuitloop.spec import Spec, load_spec
from circuitloop.specgen import generate_spec, sanity

from .conftest import needs_ngspice
from .helpers import EXAMPLES

runner = CliRunner()
EXAMPLE_NAMES = ["ldo_5v", "ne555_blinker", "opamp_x10", "usb_boost_12v"]


def _raw(example: str) -> dict:
    return yaml.safe_load((EXAMPLES / example / "spec.yaml").read_text())


def test_examples_are_sane():
    for ex in EXAMPLE_NAMES:
        assert sanity(load_spec(EXAMPLES / ex / "spec.yaml")) == [], ex


def test_sanity_catches_unusable_specs():
    raw = _raw("usb_boost_12v")
    raw["loads"] = []
    raw["transient"]["step"] = 1e-5
    problems = sanity(Spec.model_validate(raw))
    assert any("no load" in p for p in problems)
    assert any("transient.step" in p for p in problems)
    raw = _raw("ne555_blinker")
    raw["transient"].update(stop=3.0, settle=2.0)
    assert any("3 periods" in p for p in sanity(Spec.model_validate(raw)))


def _mock(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "script"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    steps = [{"role": "specwriter", "file": name} for name in files]
    (d / "script.yaml").write_text(yaml.safe_dump({"steps": steps}))
    return d


def _spec_text(example: str, **changes) -> str:
    raw = _raw(example)
    raw.update(changes)
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def test_rejected_spec_is_sent_back_with_the_problems(tmp_path):
    bad = _spec_text("usb_boost_12v", loads=[])
    good = _spec_text("usb_boost_12v", assumptions=["USB charger rated 2.4 A"])
    agent = MockBackend(_mock(tmp_path, {"bad.yaml": bad, "good.yaml": good}))
    res = generate_spec("usb 5v to 12v boost", tmp_path / "work", agent, load_db(), 60, log=lambda m: None)
    assert res.ok and res.attempts == 2
    assert res.spec.assumptions == ["USB charger rated 2.4 A"]
    second = (tmp_path / "work" / "agent" / "attempt_02" / "prompt.md").read_text()
    assert "usb 5v to 12v boost" in second and "no load" in second


def test_gives_up_after_the_attempt_limit(tmp_path):
    bad = "name: x\n"
    agent = MockBackend(_mock(tmp_path, {"a.yaml": bad, "b.yaml": bad, "c.yaml": bad}))
    res = generate_spec("anything", tmp_path / "work", agent, load_db(), 60, log=lambda m: None)
    assert not res.ok and res.attempts == 3 and res.problems


def test_cli_new_writes_a_project(tmp_path, monkeypatch):
    script = _mock(tmp_path, {"s.yaml": _spec_text("usb_boost_12v", assumptions=["Iout 0.5 A"])})
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(
        app,
        ["new", "usb 5v -> 12v boost", "--agent", "mock", "--no-run"],
        env={"CLOOP_MOCK_DIR": str(script)},
    )
    assert res.exit_code == EXIT_OK, res.output
    proj = tmp_path / "usb_boost_12v"
    assert load_spec(proj / "spec.yaml").assumptions == ["Iout 0.5 A"]
    assert 'backend = "mock"' in (proj / "cloop.toml").read_text()
    assert (proj / "spec_gen" / "agent" / "attempt_01" / "prompt.md").is_file()
    assert "usb 5v -> 12v boost" in (proj / "request.md").read_text()
    assert "Iout 0.5 A" in res.output


def test_cli_new_reports_failure(tmp_path, monkeypatch):
    script = _mock(tmp_path, {"a.yaml": "x: 1\n", "b.yaml": "x: 1\n", "c.yaml": "x: 1\n"})
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["new", "something", "--agent", "mock"], env={"CLOOP_MOCK_DIR": str(script)})
    assert res.exit_code == EXIT_DESIGN_FAILED


@needs_ngspice
def test_cli_new_runs_the_pipeline(tmp_path, monkeypatch):
    """Spec from the (mock) agent with a topology hint: the whole run needs no further agent call."""
    spec = _spec_text("opamp_x10", topology={"name": "noninverting_amp"}, assumptions=["8-10 V supply"])
    script = _mock(tmp_path, {"s.yaml": spec})
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(
        app, ["new", "x10 amplifier", "--agent", "mock", "--yes"], env={"CLOOP_MOCK_DIR": str(script)}
    )
    assert res.exit_code == EXIT_OK, res.output
    report = (tmp_path / "opamp_x10" / "output" / "final_report.md").read_text()
    assert "Assumptions in the specification" in report and "8-10 V supply" in report


def test_spec_check_cli(tmp_path):
    res = runner.invoke(app, ["spec", "check", str(EXAMPLES / "usb_boost_12v" / "spec.yaml")])
    assert res.exit_code == EXIT_OK and "mc34063_boost" in res.output
    p = tmp_path / "spec.yaml"
    p.write_text(_spec_text("usb_boost_12v", loads=[]))
    assert runner.invoke(app, ["spec", "check", str(p)]).exit_code == EXIT_ENV_ERROR


def test_specwriter_permissions(tmp_path):
    task = AgentTask("specwriter", "x", tmp_path, ["spec.yaml"], tmp_path / "log")
    cmd = ClaudeBackend().command(task)
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "Bash(cloop spec check *)" in allowed and "Bash(cloop verify *)" not in allowed
    assert f"Edit(/{(tmp_path / 'spec.yaml').resolve()})" in allowed
