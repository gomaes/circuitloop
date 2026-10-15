"""G1: design.py executes and produces a parseable KiCad netlist."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..netlist import Netlist, NetlistError, read_netlist
from ..spec import Spec
from .base import Finding, GateResult, Severity, Status

_ERC_LINE = re.compile(r"^ERC (ERROR|WARNING): (.*)$")
_NOISE = re.compile(
    r"SYMBOL_DIR environment variable|fp-lib-table file was not found|Missing tag on|Random tag"
)


def _clean(stderr: str) -> list[str]:
    return [ln for ln in stderr.strip().splitlines() if not _NOISE.search(ln)]


@dataclass
class BuildOutput:
    result: GateResult
    netlist: Netlist | None = None
    netlist_path: Path | None = None
    skidl_erc: list[tuple[str, str]] = field(default_factory=list)  # (level, message)


def run_g1(
    design: Path,
    out_dir: Path,
    spec: Spec,
    project_dir: Path,
    parts_path: str | None = None,
    timeout: int = 120,
) -> BuildOutput:
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist_path = out_dir / "circuit.net"
    if netlist_path.exists():
        netlist_path.unlink()
    env = dict(os.environ)
    env.update(
        CLOOP_NETLIST=str(netlist_path),
        CLOOP_POWER_NETS=",".join(sorted({spec.power_input.pos_net, spec.ground_net})),
        CLOOP_PROJECT_DIR=str(project_dir),
        PYTHONDONTWRITEBYTECODE="1",
    )
    if parts_path:
        env["CLOOP_PARTS_PATH"] = parts_path
    # -I: isolated mode, the design directory is NOT put on sys.path so a design
    # cannot shadow circuitloop's own modules.
    cmd = [sys.executable, "-I", str(design.resolve())]
    title = "build (design.py -> netlist)"
    try:
        proc = subprocess.run(cmd, cwd=out_dir, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        f = Finding("g1.timeout", Severity.ERROR, f"design.py did not finish within {timeout}s")
        return BuildOutput(GateResult("G1", title, Status.FAIL, [f]))
    (out_dir / "design_stdout.txt").write_text(proc.stdout)
    (out_dir / "design_stderr.txt").write_text(proc.stderr)
    erc = [
        (m.group(1), m.group(2)) for line in proc.stderr.splitlines() if (m := _ERC_LINE.match(line.strip()))
    ]
    if proc.returncode != 0:
        tail = "\n".join(_clean(proc.stderr)[-15:])
        f = Finding(
            "g1.exec",
            Severity.ERROR,
            f"design.py exited with code {proc.returncode}:\n{tail}",
            hint="Fix the Python error. Only parts from the parts DB can be used (part('KEY', value)).",
        )
        return BuildOutput(GateResult("G1", title, Status.FAIL, [f]), skidl_erc=erc)
    if not netlist_path.is_file():
        f = Finding(
            "g1.no_netlist",
            Severity.ERROR,
            "design.py ran but no netlist was written",
            hint="Call finish() at the end of design.py.",
        )
        return BuildOutput(GateResult("G1", title, Status.FAIL, [f]), skidl_erc=erc)
    try:
        nl = read_netlist(netlist_path)
    except (NetlistError, OSError) as e:
        f = Finding("g1.parse", Severity.ERROR, f"netlist could not be parsed: {e}")
        return BuildOutput(GateResult("G1", title, Status.FAIL, [f]), skidl_erc=erc)
    if not nl.components:
        f = Finding("g1.empty", Severity.ERROR, "netlist contains no components")
        return BuildOutput(GateResult("G1", title, Status.FAIL, [f]), nl, netlist_path, erc)
    metrics = {"components": len(nl.components), "nets": len(nl.nets)}
    return BuildOutput(GateResult("G1", title, Status.PASS, metrics=metrics), nl, netlist_path, erc)
