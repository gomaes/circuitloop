"""Agent backend abstraction.

An agent is a *component* called once per pipeline step: it reads TASK.md in its
working directory and writes the files it is allowed to write (design.py or
review.md). It never decides pass/fail and never controls the loop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path

KICKOFF = (
    "Read TASK.md in the current directory and carry out the task exactly as written. "
    "Only create or modify the files TASK.md says you may write. When you are done, reply with a short "
    "summary of what you changed."
)


@dataclass
class AgentTask:
    role: str  # "designer" | "reviewer"
    instructions: str  # full TASK.md content
    workdir: Path
    writable: list[str]  # file names (relative to workdir) the agent may write
    log_dir: Path
    timeout: int = 900
    env: dict[str, str] = field(default_factory=dict)  # extra environment (budget, agent mode)


@dataclass
class AgentResult:
    ok: bool
    returncode: int | None
    duration_s: float
    summary: str = ""
    error: str = ""
    cost_usd: float | None = None
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class AgentError(Exception):
    pass


class AgentBackend(ABC):
    name = "abstract"
    executable: str | None = None

    def __init__(
        self,
        model: str | None = None,
        extra_args: list[str] | None = None,
        max_budget_usd: float | None = None,
    ):
        self.model = model
        self.extra_args = list(extra_args or [])
        self.max_budget_usd = max_budget_usd

    @property
    def label(self) -> str:
        """Backend and model as shown in logs and run state, e.g. ``claude:haiku``."""
        return f"{self.name}:{self.model}" if self.model else self.name

    def available(self) -> bool:
        return self.executable is None or shutil.which(self.executable) is not None

    def run(self, task: AgentTask) -> AgentResult:
        task.workdir.mkdir(parents=True, exist_ok=True)
        task.log_dir.mkdir(parents=True, exist_ok=True)
        (task.workdir / "TASK.md").write_text(task.instructions)
        (task.log_dir / "prompt.md").write_text(task.instructions)
        res = self._run(task)
        (task.log_dir / "result.json").write_text(json.dumps(res.to_dict(), indent=2))
        return res

    @abstractmethod
    def _run(self, task: AgentTask) -> AgentResult: ...

    # helpers ---------------------------------------------------------------
    def _env(self, task: AgentTask | None = None) -> dict[str, str]:
        env = dict(os.environ)
        # make `cloop` (same installation) available for self-checks
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        if task is not None:
            env.update(task.env)
        return env

    def _spawn(
        self, cmd: list[str], task: AgentTask, stdin: str | None, env: dict[str, str]
    ) -> tuple[int | None, str, str, float, str]:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=task.workdir,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=task.timeout,
                env=env,
            )
            rc, out, err, msg = proc.returncode, proc.stdout, proc.stderr, ""
        except subprocess.TimeoutExpired as e:
            rc, msg = None, f"agent timed out after {task.timeout}s"
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        except OSError as e:
            rc, out, err, msg = None, "", "", f"could not start agent: {e}"
        dt = time.monotonic() - t0
        (task.log_dir / "stdout.txt").write_text(out)
        (task.log_dir / "stderr.txt").write_text(err)
        (task.log_dir / "command.json").write_text(json.dumps(cmd, indent=2))
        return rc, out, err, dt, msg
