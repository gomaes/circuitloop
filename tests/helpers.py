from __future__ import annotations

import textwrap
from pathlib import Path

from circuitloop.gates import VerifyContext, verify
from circuitloop.partsdb import load_db
from circuitloop.spec import load_spec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def run_design(
    tmp_path: Path,
    example: str,
    code: str,
    phase: int = 1,
    faults: bool = False,
    baseline: dict | None = None,
    project_dir: Path | None = None,
    spec_path: Path | None = None,
):
    proj = project_dir or (EXAMPLES / example)
    spec = load_spec(spec_path or (EXAMPLES / example / "spec.yaml"))
    tmp_path.mkdir(parents=True, exist_ok=True)
    design = tmp_path / "design.py"
    design.write_text(textwrap.dedent(code))
    ctx = VerifyContext(spec, load_db(proj), proj)
    return verify(design, tmp_path / "work", ctx, phase=phase, faults=faults, baseline=baseline)


def reference(example: str, which: str) -> str:
    return (EXAMPLES / example / "reference" / f"{which}_design.py").read_text()


def rules_hit(outcome, gate: str) -> set[str]:
    g = outcome.report.gate(gate)
    return {f.rule for f in g.findings if str(f.severity) == "error"} if g else set()
