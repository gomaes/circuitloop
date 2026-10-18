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


_FAMILIES = {
    "apt": {"debian", "ubuntu", "linuxmint", "pop", "raspbian"},
    "dnf": {"fedora", "rhel", "centos", "rocky", "almalinux"},
    "pacman": {"arch", "archarm", "manjaro", "endeavouros", "cachyos", "garuda", "artix"},
}
_PM_EXE = {"apt": "apt-get", "dnf": "dnf", "pacman": "pacman"}


def distro_family(os_release: Path = Path("/etc/os-release"), probe: bool = True) -> str:
    """Return 'apt', 'dnf', 'pacman' or 'unknown'.

    Uses ID / ID_LIKE from os-release (Arch derivatives such as Manjaro, EndeavourOS
    and CachyOS report ``ID_LIKE=arch``); falls back to the package manager on PATH.
    """
    tokens: set[str] = set()
    try:
        for line in os_release.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                if key in ("ID", "ID_LIKE"):
                    tokens |= set(val.strip().strip('"').lower().split())
    except OSError:
        pass
    for fam, ids in _FAMILIES.items():
        if tokens & ids:
            return fam
    if probe:
        for fam, exe in _PM_EXE.items():
            if shutil.which(exe):
                return fam
    return "unknown"


INSTALL_CMD = {
    "apt": "sudo apt install {pkgs}",
    "dnf": "sudo dnf install {pkgs}",
    "pacman": "sudo pacman -S --needed {pkgs}",
}
# distro package names for the tools circuitloop needs
PACKAGES = {
    "ngspice": {"apt": "ngspice", "dnf": "ngspice", "pacman": "ngspice"},
    "npm": {"apt": "nodejs npm", "dnf": "nodejs npm", "pacman": "nodejs npm"},
}


def install_hint(tool: str, fam: str) -> str:
    pkgs = PACKAGES[tool].get(fam)
    if fam in INSTALL_CMD and pkgs:
        return INSTALL_CMD[fam].format(pkgs=pkgs)
    if tool == "ngspice":
        return "install ngspice from your distribution or https://ngspice.sourceforge.io/download.html"
    return f"install {tool} with your distribution's package manager"


def broken_hint(problem: str, fam: str) -> str:
    """How to repair an installed but non-working ngspice."""
    if re.search(r"GLIBC|GLIBCXX|not found \(required by|shared libraries|symbol lookup", problem):
        if fam == "pacman":
            return (
                "the ngspice package was built for newer system libraries than are installed — a partial "
                "upgrade. Run a full upgrade: sudo pacman -Syu (never `pacman -Sy <pkg>` alone)"
            )
        if fam == "apt":
            return "library mismatch: reinstall ngspice from your release: sudo apt update && sudo apt install --reinstall ngspice"
        if fam == "dnf":
            return "library mismatch: sudo dnf upgrade --refresh && sudo dnf reinstall ngspice"
        return "library mismatch: reinstall ngspice from the same release as your system libraries"
    return "reinstall ngspice (" + install_hint("ngspice", fam) + ") and check `ngspice -b` on a small deck"


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
        from .sim.ngspice import smoke_test

        problem = smoke_test()
        if problem is None:
            v = _version(["ngspice", "--version"], r"ngspice-(\S+)")
            checks.append(Check("ngspice", True, True, f"ngspice {v} (test simulation ok)"))
        else:
            checks.append(Check("ngspice", False, True, problem, broken_hint(problem, fam)))
    else:
        checks.append(Check("ngspice", False, True, "not found in PATH", install_hint("ngspice", fam)))

    for mod in ("skidl", "matplotlib", "yaml", "pydantic", "typer"):
        ok = importlib.util.find_spec(mod) is not None
        checks.append(
            Check(f"python:{mod}", ok, True, "importable" if ok else "missing", "reinstall: ./install.sh")
        )

    npm_pre = "" if shutil.which("npm") else f"{install_hint('npm', fam)} && "
    agents = {
        "claude": (
            ["claude", "--version"],
            r"(\d+\.\d+\.\d+)",
            f"{npm_pre}npm install -g @anthropic-ai/claude-code  (see https://docs.claude.com/claude-code)",
        ),
        "opencode": (
            ["opencode", "--version"],
            r"(\d+\.\d+\.\d+)",
            f"{npm_pre}npm install -g opencode-ai  (see https://opencode.ai/docs)",
        ),
    }
    for name, (cmd, pat, hint) in agents.items():
        required = agent == name
        if shutil.which(cmd[0]):
            checks.append(Check(f"agent:{name}", True, required, _version(cmd, pat) or "found"))
        else:
            checks.append(Check(f"agent:{name}", False, required, "not found in PATH", hint))
    return checks
