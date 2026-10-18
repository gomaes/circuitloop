"""End-to-end pipeline tests with the scripted (mock) agent — no LLM calls."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rich.console import Console

from circuitloop import EXIT_DESIGN_FAILED, EXIT_OK, EXIT_TAMPERED
from circuitloop.agents.mock import MockBackend
from circuitloop.config import Config
from circuitloop.orchestrator import Orchestrator, RunState, latest_run

from .conftest import FIXTURES, needs_ngspice
from .helpers import EXAMPLES

pytestmark = needs_ngspice
MOCK = FIXTURES / "mock"


def _project(tmp_path: Path, example: str = "ldo_5v") -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(EXAMPLES / example / "spec.yaml", proj / "spec.yaml")
    return proj


def _script(tmp_path: Path, steps: list[dict]) -> MockBackend:
    d = tmp_path / "script"
    d.mkdir(exist_ok=True)
    for f in MOCK.iterdir():
        shutil.copy(f, d / f.name)
    for ex in ("ldo_5v",):
        for p in (EXAMPLES / ex / "reference").glob("*.py"):
            shutil.copy(p, d / f"{ex}_{p.name}")
    import yaml

    (d / "script.yaml").write_text(yaml.safe_dump({"steps": steps}))
    return MockBackend(d)


def _orch(proj: Path, agent: MockBackend, max_iter: int = 3) -> Orchestrator:
    cfg = Config()
    cfg.loop.max_iter = max_iter
    return Orchestrator(proj / "spec.yaml", cfg, agent, console=Console(quiet=True))


GOOD = [
    {"role": "designer", "file": "ldo_broken.py"},
    {"role": "designer", "file": "ldo_5v_phase1_design.py"},
    {"role": "reviewer", "file": "review.md"},
    {"role": "designer", "file": "ldo_5v_hardened_design.py"},
]


def test_full_pipeline_passes(tmp_path):
    proj = _project(tmp_path)
    agent = _script(tmp_path, GOOD)
    code = _orch(proj, agent).run()
    assert code == EXIT_OK
    rd = latest_run(proj)
    st = RunState.load(rd)
    assert st.status == "passed"
    assert [p for p in ("design", "harden", "reverify", "output") if st.phases[p]["status"] != "passed"] == []
    iters = sorted(p.name for p in rd.glob("iter_*"))
    assert len(iters) == 5  # broken, fixed, review, harden, reverify
    first = rd / iters[0]
    assert (first / "agent" / "prompt.md").is_file()
    assert (first / "report.json").is_file() and not json.loads((first / "report.json").read_text())["passed"]
    assert (first / "work" / "ref" / "parts_catalog.md").is_file()
    assert (rd / "baseline.json").is_file()
    assert not list(rd.rglob("*.raw"))  # raw waveforms are pruned (keep_raw = false)
    assert list(rd.rglob("deck.cir"))
    for f in ("final_report.md", "layout.html", "bom.csv", "build_guide.md", "schematic.svg", "ldo_5v.net"):
        assert (proj / "output" / f).is_file(), f
    assert (rd / "output" / "layout.html").is_file()
    # the fix prompt contains the failure report
    second = rd / iters[1]
    assert "erc.decoupling" in (second / "agent" / "prompt.md").read_text()


def test_loop_limit_exit_1(tmp_path):
    proj = _project(tmp_path)
    agent = _script(tmp_path, [{"role": "designer", "file": "ldo_broken.py"}] * 3)
    code = _orch(proj, agent, max_iter=2).run()
    assert code == EXIT_DESIGN_FAILED
    rd = latest_run(proj)
    assert (rd / "failure_report.md").is_file()
    assert "erc.decoupling" in (rd / "failure_report.md").read_text()
    assert len(list(rd.glob("iter_*"))) == 3  # initial + 2 fixes
    assert RunState.load(rd).status == "failed"


def test_tamper_readonly_copy_exit_3(tmp_path):
    proj = _project(tmp_path)
    agent = _script(
        tmp_path, [{"role": "designer", "file": "ldo_5v_phase1_design.py", "tamper": "ref/spec.yaml"}]
    )
    assert _orch(proj, agent).run() == EXIT_TAMPERED
    rd = latest_run(proj)
    assert (rd / "TAMPER_REPORT.md").is_file()
    assert RunState.load(rd).status == "tampered"


def test_tamper_project_spec_exit_3(tmp_path):
    proj = _project(tmp_path)
    agent = _script(
        tmp_path, [{"role": "designer", "file": "ldo_5v_phase1_design.py", "tamper": "../../../../spec.yaml"}]
    )
    assert _orch(proj, agent).run() == EXIT_TAMPERED
    assert "spec.yaml" in (latest_run(proj) / "TAMPER_REPORT.md").read_text()


def test_tamper_new_rule_file_exit_3(tmp_path):
    proj = _project(tmp_path)
    (proj / "rules").mkdir()
    agent = _script(
        tmp_path,
        [{"role": "designer", "file": "ldo_5v_phase1_design.py", "tamper": "../../../../rules/sneaky.py"}],
    )
    assert _orch(proj, agent).run() == EXIT_TAMPERED


def test_agent_failure_counts_as_attempt(tmp_path):
    proj = _project(tmp_path)
    agent = _script(tmp_path, [])  # exhausted immediately: agent errors, no design
    assert _orch(proj, agent, max_iter=1).run() == EXIT_DESIGN_FAILED
    assert "no_design" in (latest_run(proj) / "failure_report.md").read_text()


def test_resume_from_harden(tmp_path):
    proj = _project(tmp_path)
    agent = _script(
        tmp_path,
        GOOD[1:2]
        + [
            {"role": "reviewer", "file": "review.md"},
            {"role": "designer", "file": "ldo_5v_phase1_design.py"},
        ],
    )
    # hardened step returns the unprotected design -> protection rule fails, script exhausted -> fail
    assert _orch(proj, agent, max_iter=1).run() == EXIT_DESIGN_FAILED
    assert RunState.load(latest_run(proj)).phases["design"]["status"] == "passed"
    agent2 = _script(tmp_path, GOOD[2:])
    assert _orch(proj, agent2).run("harden") == EXIT_OK
    st = RunState.load(latest_run(proj))
    assert st.status == "passed"


@needs_ngspice
def test_pipeline_with_topology_hint_needs_no_agent(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    import yaml

    raw = yaml.safe_load((EXAMPLES / "opamp_x10" / "spec.yaml").read_text())
    raw["topology"] = {"name": "noninverting_amp"}
    (proj / "spec.yaml").write_text(yaml.safe_dump(raw))
    script = tmp_path / "script"
    script.mkdir()
    (script / "script.yaml").write_text("steps: []\n")  # any agent call would fail
    code = Orchestrator(proj / "spec.yaml", Config(), MockBackend(script), console=Console(quiet=True)).run()
    assert code == EXIT_OK
    st = RunState.load(latest_run(proj))
    assert {i["role"] for i in st.iterations} == {"topology", "verify"}
    assert (proj / "output" / "final_report.md").is_file()
    shutil.rmtree(proj / "runs")
