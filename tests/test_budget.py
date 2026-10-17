"""Per-step agent budget enforced by `cloop verify`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from circuitloop import EXIT_ENV_ERROR
from circuitloop.cli import app

from .conftest import needs_ngspice
from .helpers import EXAMPLES, reference

runner = CliRunner()


def test_no_budget_outside_agent_steps(monkeypatch):
    from circuitloop import budget

    monkeypatch.delenv(budget.ENV_FILE, raising=False)
    assert budget.from_env() is None


def test_deadline_refuses(tmp_path):
    from circuitloop.budget import Budget, consume

    b = Budget(5, tmp_path / "n.json", deadline=0.0)
    ok, msg = consume(b, "x")
    assert not ok and "time left" in msg


@needs_ngspice
def test_self_check_budget(tmp_path):
    design = tmp_path / "design.py"
    design.write_text(reference("opamp_x10", "phase1"))
    counter = tmp_path / "log" / "self_checks.json"
    env = {
        "CLOOP_AGENT_WORKDIR": str(tmp_path),
        "CLOOP_SELF_CHECK_LIMIT": "1",
        "CLOOP_SELF_CHECK_FILE": str(counter),
    }
    args = [
        "verify",
        str(design),
        "--spec",
        str(EXAMPLES / "opamp_x10" / "spec.yaml"),
        "--phase",
        "design",
        "--out",
        str(tmp_path / "c"),
    ]
    first = runner.invoke(app, args, env=env)
    assert first.exit_code == 0, first.output
    assert "self-check 1 of 1" in first.output and "--quick applied" in first.output
    assert "quick check" in (tmp_path / "c" / "report.md").read_text()
    second = runner.invoke(app, args, env=env)
    assert second.exit_code == EXIT_ENV_ERROR
    assert len(json.loads(counter.read_text())) == 1
