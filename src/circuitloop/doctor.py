"""Environment checks for `cloop doctor`."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MIN_PY = (3, 11)


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    detail: str
    hint: str = ""


def distro_family(os_release: Path = Path("/etc/os-release")) -> str:
    """Return 'apt', 'dnf', 'pacman' or 'unknown'."""
    try:
        text = os_release.read_text()
    except OSError:
        return "unknown"
    fields = dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
    )
    ids = " ".join(fields.get(k, "").strip('"').lower() for k in ("ID", "ID_LIKE"))
    if any(x in ids for x in ("ubuntu", "debian")):
        return "apt"
    if any(x in ids for x in ("fedora", "rhel", "centos")):
        return "dnf"
    if any(x in ids for x in ("arch", "manjaro")):
        return "pacman"
    return "unknown"


NGSPICE_HINTS = {
    "apt": "sudo apt install ngspice",
    "dnf": "sudo dnf install ngspice",
    "pacman": "sudo pacman -S ngspice",
    "unknown": "install ngspice from your distribution or https://ngspice.sourceforge.io/download.html",
}


def _version(cmd: list[str], pattern: str) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(pattern, out.stdout + out.stderr)
    return m.group(1) if m else (out.stdout.strip().splitlines() or ["?"])[0]


def run_checks(agent: str | None = None) -> list[Check]:
    fam = distro_family()
    checks: list[Check] = []

    py_ok = sys.version_info[:2] >= MIN_PY
    checks.append(
        Check("python", py_ok, True, sys.version.split()[0], "" if py_ok else "Python 3.11+ is required")
    )

    if shutil.which("ngspice"):
        v = _version(["ngspice", "--version"], r"ngspice-(\S+)")
        checks.append(Check("ngspice", True, True, f"ngspice {v}"))
    else:
        checks.append(Check("ngspice", False, True, "not found in PATH", NGSPICE_HINTS[fam]))

    for mod in ("skidl", "matplotlib", "yaml", "pydantic", "typer"):
        ok = importlib.util.find_spec(mod) is not None
        checks.append(
            Check(f"python:{mod}", ok, True, "importable" if ok else "missing", "reinstall: ./install.sh")
        )

    agents = {
        "claude": (
            ["claude", "--version"],
            r"(\d+\.\d+\.\d+)",
            "npm install -g @anthropic-ai/claude-code  (see https://docs.claude.com/claude-code)",
        ),
        "opencode": (
            ["opencode", "--version"],
            r"(\d+\.\d+\.\d+)",
            "npm install -g opencode-ai  (see https://opencode.ai/docs)",
        ),
    }
    for name, (cmd, pat, hint) in agents.items():
        required = agent == name
        if shutil.which(cmd[0]):
            checks.append(Check(f"agent:{name}", True, required, _version(cmd, pat) or "found"))
        else:
            checks.append(Check(f"agent:{name}", False, required, "not found in PATH", hint))
    return checks
