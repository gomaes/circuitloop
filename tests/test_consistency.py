"""Contradictory fault expectations are found before any design work (spec writing, spec check, run)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from rich.console import Console

from circuitloop import EXIT_SPEC_INFEASIBLE
from circuitloop.agents.mock import MockBackend
from circuitloop.config import Config
from circuitloop.consistency import fault_conflicts
from circuitloop.orchestrator import Orchestrator, RunState, latest_run
from circuitloop.partsdb import load_db
from circuitloop.spec import Spec, load_spec
from circuitloop.specgen import generate_spec, sanity

from .conftest import FIXTURES
from .helpers import EXAMPLES

BAD = FIXTURES / "specs" / "contradictory_fault.yaml"


def _with(path: Path, change) -> Spec:
    raw = yaml.safe_load(path.read_text())
    change(raw)
    return Spec.model_validate(raw)


def test_examples_have_no_conflicts():
    for d in EXAMPLES.iterdir():
        if (d / "spec.yaml").is_file():
            assert fault_conflicts(load_spec(d / "spec.yaml")) == [], d.name


def test_contradiction_found_with_both_fixes():
    (c,) = fault_conflicts(load_spec(BAD))
    assert c.fault == "reverse_12v"
    msg = str(c)
    assert "max_input_current is 0.01 A" in msg and "raise max_input_current to >= 0.9" in msg
    assert "let VOUT go down to" in msg
    assert any("contradict" in p for p in sanity(load_spec(BAD)))  # spec writer / spec check see it


def test_each_suggested_fix_removes_the_contradiction():
    (c,) = fault_conflicts(load_spec(BAD))
    new_min = float(c.message.split("let VOUT go down to ")[1].split(" V")[0])
    i_need = float(c.message.split("raise max_input_current to >= ")[1].split(" A")[0])

    def lower_vout(raw):
        raw["faults"][0]["expect"]["nets"]["VOUT"]["min"] = new_min - 0.01

    def more_current(raw):
        raw["faults"][0]["expect"]["max_input_current"] = i_need * 1.01

    def no_current_limit(raw):
        del raw["faults"][0]["expect"]["max_input_current"]

    for fix in (lower_vout, more_current, no_current_limit):
        assert fault_conflicts(_with(BAD, fix)) == [], fix.__name__
    # just short of the suggested bound is still contradictory: the suggestion is tight
    assert fault_conflicts(
        _with(BAD, lambda r: r["faults"][0]["expect"]["nets"]["VOUT"].update(min=new_min + 0.2))
    )


@pytest.mark.parametrize(
    "change, text",
    [
        (lambda r: r["faults"][0]["expect"]["nets"].update(VOUT={"min": 2, "max": 1}), "is above max"),
        (lambda r: r["faults"][0]["expect"]["nets"].update(GND={"min": 0.5}), "ground (0 V)"),
        (lambda r: r["faults"][0]["expect"]["nets"].update(VIN={"min": -1.0}), "the supply net at -12 V"),
    ],
)
def test_impossible_single_limits(change, text):
    assert any(text in str(c) for c in fault_conflicts(_with(BAD, change)))


def _mock(tmp_path: Path, steps: list[dict]) -> MockBackend:
    d = tmp_path / "script"
    d.mkdir()
    fixed = yaml.safe_load(BAD.read_text())
    fixed["faults"][0]["expect"]["nets"]["VOUT"]["min"] = -13.0  # VOUT follows the reversed supply
    fixed["assumptions"] = ["Under reverse polarity VOUT follows the supply through the motor."]
    shutil.copy(BAD, d / "bad.yaml")
    (d / "fixed.yaml").write_text(yaml.safe_dump(fixed, sort_keys=False))
    (d / "script.yaml").write_text(yaml.safe_dump({"steps": steps}))
    return MockBackend(d)


def test_spec_writer_gets_the_contradiction_and_fixes_it(tmp_path):
    agent = _mock(
        tmp_path, [{"role": "specwriter", "file": "bad.yaml"}, {"role": "specwriter", "file": "fixed.yaml"}]
    )
    res = generate_spec("motor driver", tmp_path / "w", agent, load_db(), 60, log=lambda m: None)
    assert res.ok and res.attempts == 2
    prompt2 = (tmp_path / "w" / "agent" / "attempt_02" / "prompt.md").read_text()
    assert "contradict each other" in prompt2 and "let VOUT go down to" in prompt2
    assert fault_conflicts(res.spec) == []


def test_run_stops_before_designing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(BAD, proj / "spec.yaml")
    agent = _mock(tmp_path, [])
    code = Orchestrator(proj / "spec.yaml", Config(), agent, console=Console(quiet=True)).run()
    assert code == EXIT_SPEC_INFEASIBLE and agent.calls == 0
    rd = latest_run(proj)
    st = RunState.load(rd)
    assert st.status == "infeasible" and st.iterations == []
    assert "let VOUT go down to" in (rd / "spec_infeasible.md").read_text()
