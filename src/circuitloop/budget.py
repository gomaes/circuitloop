"""Per-step agent budget: number of `cloop verify` self-checks and wall-clock deadline.

The orchestrator passes the budget to the agent process through the environment; the counter file
lives in the iteration's log directory, outside the agent's writable work directory. `cloop verify`
run inside an agent step consumes one self-check, is always a quick check, and refuses once the
budget or the time is used up — the pipeline then verifies the design authoritatively itself.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

ENV_WORKDIR = "CLOOP_AGENT_WORKDIR"
ENV_LIMIT = "CLOOP_SELF_CHECK_LIMIT"
ENV_FILE = "CLOOP_SELF_CHECK_FILE"
ENV_DEADLINE = "CLOOP_AGENT_DEADLINE"
MIN_TIME_LEFT = 60  # seconds: below this a self-check would only delay the authoritative run


@dataclass
class Budget:
    limit: int
    file: Path
    deadline: float | None

    def env(self, workdir: Path) -> dict[str, str]:
        out = {ENV_WORKDIR: str(workdir.resolve()), ENV_LIMIT: str(self.limit), ENV_FILE: str(self.file)}
        if self.deadline is not None:
            out[ENV_DEADLINE] = f"{self.deadline:.0f}"
        return out


def from_env() -> Budget | None:
    if ENV_FILE not in os.environ:
        return None
    dl = os.environ.get(ENV_DEADLINE)
    return Budget(int(os.environ.get(ENV_LIMIT, "0")), Path(os.environ[ENV_FILE]), float(dl) if dl else None)


def records(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return []


def consume(b: Budget, args: str) -> tuple[bool, str]:
    """Use one self-check. Returns (allowed, message for the agent)."""
    used = records(b.file)
    left = None if b.deadline is None else b.deadline - time.time()
    if len(used) >= b.limit:
        return False, (
            f"self-check budget used up ({len(used)} of {b.limit}). Stop here and finish your answer: "
            "the pipeline now runs the complete verification of design.py itself and reports back."
        )
    if left is not None and left < MIN_TIME_LEFT:
        return False, (
            f"only {max(left, 0):.0f} s of this step's time left. Stop here: the pipeline verifies "
            "design.py itself."
        )
    used.append({"t": time.time(), "args": args})
    b.file.parent.mkdir(parents=True, exist_ok=True)
    b.file.write_text(json.dumps(used, indent=1))
    msg = f"self-check {len(used)} of {b.limit}"
    if left is not None:
        msg += f", ~{left / 60:.0f} min left in this step"
    return True, msg
