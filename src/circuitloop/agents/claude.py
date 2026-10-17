"""Claude Code backend: ``claude -p`` (headless print mode).

Options verified against ``claude --help`` (2.1.x): --output-format json,
--permission-mode dontAsk (denies anything not pre-approved), --allowedTools
with path-scoped Edit rules (Write is governed by Edit rules),
--no-session-persistence, --max-budget-usd, --model.
"""

from __future__ import annotations

import json

from .base import KICKOFF, AgentBackend, AgentResult, AgentTask


class ClaudeBackend(AgentBackend):
    name = "claude"
    executable = "claude"

    def command(self, task: AgentTask) -> list[str]:
        # Anchor the writable files absolutely ("//" prefix): a "./" rule is resolved against the
        # session's *current* directory, which moves when the agent runs commands elsewhere.
        allowed = ["Read", "Grep", "Glob"] + [f"Edit(/{(task.workdir / w).resolve()})" for w in task.writable]
        if task.role == "designer":
            allowed += ["Bash(cloop verify *)", "Bash(cloop topology *)"]
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--allowedTools",
            ",".join(allowed),
            "--disallowedTools",
            "WebFetch,WebSearch",
        ]
        if self.model:
            cmd += ["--model", self.model]
        if self.max_budget_usd:
            cmd += ["--max-budget-usd", str(self.max_budget_usd)]
        return cmd + self.extra_args

    def _run(self, task: AgentTask) -> AgentResult:
        cmd = self.command(task)
        rc, out, err, dt, msg = self._spawn(cmd, task, KICKOFF, self._env(task))
        summary, cost, is_error = "", None, rc != 0
        try:
            data = json.loads(out)
            summary = str(data.get("result", ""))
            cost = data.get("total_cost_usd")
            is_error = is_error or bool(data.get("is_error"))
        except (json.JSONDecodeError, AttributeError):
            summary = out[-2000:]
        error = msg or (err.strip()[-2000:] if is_error else "")
        return AgentResult(
            ok=(rc == 0 and not is_error),
            returncode=rc,
            duration_s=dt,
            summary=summary,
            error=error,
            cost_usd=cost,
            command=cmd,
        )
