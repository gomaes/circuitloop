"""Scripted agent for tests/CI: replays files from a script directory.

``<script_dir>/script.yaml``::

    steps:
      - {role: designer, file: broken.py}       # copied to the writable file
      - {role: designer, file: fixed.py}
      - {role: reviewer, file: review.md}
      - {role: designer, file: hardened.py, tamper: ref/spec.yaml}  # optional: modify a file
      - {role: designer, file: x.py, spec_issue: "why the spec cannot be met"}  # writes spec_issue.md

``tamper`` paths are relative to the agent working directory, or absolute.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .base import AgentBackend, AgentError, AgentResult, AgentTask


class MockBackend(AgentBackend):
    name = "mock"
    executable = None

    def __init__(self, script_dir: Path | str, **kw):
        super().__init__(**kw)
        self.dir = Path(script_dir)
        f = self.dir / "script.yaml"
        if not f.is_file():
            raise AgentError(f"mock agent: {f} not found")
        self.steps = list((yaml.safe_load(f.read_text()) or {}).get("steps", []))
        self.calls = 0

    def _run(self, task: AgentTask) -> AgentResult:
        if self.calls >= len(self.steps):
            return AgentResult(False, 1, 0.0, error="mock script exhausted")
        step = self.steps[self.calls]
        self.calls += 1
        if step.get("role", task.role) != task.role:
            return AgentResult(
                False, 1, 0.0, error=f"mock script expected role {step.get('role')}, got {task.role}"
            )
        if step.get("file"):
            shutil.copy(self.dir / step["file"], task.workdir / task.writable[0])
        if step.get("spec_issue"):  # the agent reports that the spec cannot be met
            (task.workdir / "spec_issue.md").write_text(step["spec_issue"])
        if step.get("tamper"):
            target = Path(step["tamper"])
            target = target if target.is_absolute() else task.workdir / target
            if target.exists():
                target.chmod(0o644)
            with target.open("a") as fh:
                fh.write("\n# tampered by agent\n")
        (task.log_dir / "stdout.txt").write_text(f"mock step {self.calls}: {step}\n")
        return AgentResult(True, 0, 0.0, summary=f"mock step {self.calls}: {step.get('file')}")
