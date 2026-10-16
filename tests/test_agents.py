"""Backend plumbing tests using fake `claude` / `opencode` executables (no LLM calls)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from circuitloop.agents import AgentTask, make_backend
from circuitloop.agents.claude import ClaudeBackend
from circuitloop.agents.opencode import OpenCodeBackend
from circuitloop.config import AgentConfig

FAKE = r"""#!/usr/bin/env python3
import json, os, sys, pathlib
log = pathlib.Path(os.environ["FAKE_LOG"])
log.write_text(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read() if not sys.stdin.isatty() else "",
                           "cwd": os.getcwd(), "oc_config": os.environ.get("OPENCODE_CONFIG_CONTENT")}))
assert pathlib.Path("TASK.md").is_file()
pathlib.Path("design.py").write_text("# written by fake agent\n")
if os.path.basename(sys.argv[0]) == "claude":
    print(json.dumps({"type": "result", "result": "done", "is_error": False, "total_cost_usd": 0.01}))
else:
    print(json.dumps({"type": "text", "part": {"type": "text", "text": "done"}}))
"""


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    for name in ("claude", "opencode"):
        p = b / name
        p.write_text(FAKE)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.json"))
    return tmp_path


def _task(tmp: Path) -> AgentTask:
    return AgentTask("designer", "# do it", tmp / "work", ["design.py"], tmp / "logs", timeout=30)


def test_claude_backend(fake_bin):
    be = ClaudeBackend(model="sonnet", max_budget_usd=1.5)
    res = be.run(_task(fake_bin))
    assert res.ok and res.summary == "done" and res.cost_usd == 0.01
    log = json.loads((fake_bin / "log.json").read_text())
    argv = log["argv"]
    assert argv[0] == "-p"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    allowed = argv[argv.index("--allowedTools") + 1]
    design = (fake_bin / "work" / "design.py").resolve()
    assert f"Edit(/{design})" in allowed and allowed.count("Edit(//") == 1
    assert "Bash(cloop verify *)" in allowed
    assert "Write" not in allowed.split(",")
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "TASK.md" in log["stdin"]
    assert (fake_bin / "work" / "design.py").is_file()
    assert (fake_bin / "logs" / "prompt.md").read_text() == "# do it"


def test_opencode_backend(fake_bin):
    be = OpenCodeBackend(model="anthropic/claude-sonnet")
    res = be.run(_task(fake_bin))
    assert res.ok and "done" in res.summary
    log = json.loads((fake_bin / "log.json").read_text())
    assert log["argv"][:3] == ["run", "--format", "json"]
    cfg = json.loads(log["oc_config"])["permission"]
    assert cfg["*"] == "deny" and cfg["edit"]["*"] == "deny" and cfg["edit"]["design.py"] == "allow"
    assert cfg["bash"]["cloop verify *"] == "allow" and cfg["webfetch"] == "deny"


def test_reviewer_has_no_bash(fake_bin):
    t = AgentTask("reviewer", "x", fake_bin / "w2", ["review.md"], fake_bin / "l2", 30)
    cmd = ClaudeBackend().command(t)
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "Bash" not in allowed and f"Edit(/{(fake_bin / 'w2' / 'review.md').resolve()})" in allowed
    assert OpenCodeBackend().permission_config(t)["permission"]["bash"] == {"*": "deny"}


def test_timeout(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    p = b / "claude"
    p.write_text("#!/bin/sh\nsleep 5\n")
    p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    t = _task(tmp_path)
    t.timeout = 1
    res = ClaudeBackend().run(t)
    assert not res.ok and "timed out" in res.error


def test_make_backend(monkeypatch, tmp_path):
    assert make_backend(AgentConfig(backend="claude")).name == "claude"
    assert make_backend(AgentConfig(backend="opencode")).name == "opencode"
    (tmp_path / "script.yaml").write_text("steps: []\n")
    monkeypatch.setenv("CLOOP_MOCK_DIR", str(tmp_path))
    assert make_backend(AgentConfig(backend="mock")).name == "mock"
