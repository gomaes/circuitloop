"""OpenCode backend: ``opencode run`` (non-interactive).

Options verified against ``opencode run --help`` (1.19): --format json,
--dir, -m provider/model. Permissions are supplied through
OPENCODE_CONFIG_CONTENT: deny by default, allow reads and edits of the
writable files only (last matching rule wins).
"""

from __future__ import annotations

import json

from .base import KICKOFF, AgentBackend, AgentResult, AgentTask


class OpenCodeBackend(AgentBackend):
    name = "opencode"
    executable = "opencode"

    def permission_config(self, task: AgentTask) -> dict:
        edit = {"*": "deny"}
        for w in task.writable:
            edit[w] = "allow"
            edit[f"*/{w}"] = "allow"
        bash = {"*": "deny"}
        if task.role == "designer":
            bash["cloop verify *"] = "allow"
        return {
            "permission": {
                "*": "deny",
                "read": "allow",
                "glob": "allow",
                "grep": "allow",
                "list": "allow",
                "edit": edit,
                "bash": bash,
                "webfetch": "deny",
                "websearch": "deny",
                "external_directory": "deny",
                "question": "deny",
                "task": "deny",
            }
        }

    def command(self, task: AgentTask) -> list[str]:
        cmd = ["opencode", "run", "--format", "json", "--dir", str(task.workdir)]
        if self.model:
            cmd += ["-m", self.model]
        return cmd + self.extra_args + [KICKOFF]

    def _run(self, task: AgentTask) -> AgentResult:
        cmd = self.command(task)
        env = self._env()
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(self.permission_config(task))
        rc, out, err, dt, msg = self._spawn(cmd, task, None, env)
        texts = []
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part") if isinstance(ev, dict) else None
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
        error = msg or (err.strip()[-2000:] if rc != 0 else "")
        return AgentResult(
            ok=rc == 0,
            returncode=rc,
            duration_s=dt,
            summary="\n".join(texts)[-4000:],
            error=error,
            command=cmd,
        )
