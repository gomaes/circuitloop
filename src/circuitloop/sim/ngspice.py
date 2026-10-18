"""Run ngspice in batch mode and parse ASCII raw files."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class SimError(Exception):
    pass


class NgspiceUnavailable(SimError):
    """ngspice itself cannot run (missing/broken installation) — an environment error, not a design error."""


# loader / exec failures: the binary never got to read the deck
_BROKEN = re.compile(
    r"error while loading shared libraries|version `[^']+' not found|not found \(required by|"
    r"cannot execute|exec format error|symbol lookup error",
    re.I,
)


@dataclass
class SimResult:
    plots: dict[str, Plot]
    op_converged: bool
    tran_error: str | None = None  # why a requested transient produced no data
    retries: int = 0  # robustness retries that were needed (0 = first attempt worked)

    def __getitem__(self, key: str) -> Plot:
        return self.plots[key]


@dataclass
class Plot:
    name: str
    vectors: dict[str, np.ndarray]

    def get(self, name: str) -> np.ndarray | None:
        return self.vectors.get(name.lower())

    @property
    def time(self) -> np.ndarray | None:
        return self.vectors.get("time")


def parse_raw(path: Path) -> Plot:
    text = path.read_text()
    m_vars = re.search(r"^Variables:\s*$", text, re.M)
    m_vals = re.search(r"^Values:\s*$", text, re.M)
    m_n = re.search(r"^No\. Variables:\s*(\d+)", text, re.M)
    m_p = re.search(r"^No\. Points:\s*(\d+)", text, re.M)
    m_name = re.search(r"^Plotname:\s*(.*)$", text, re.M)
    if not (m_vars and m_vals and m_n and m_p):
        raise SimError(f"unrecognised raw file {path}")
    nvar, npts = int(m_n.group(1)), int(m_p.group(1))
    names = []
    for line in text[m_vars.end() : m_vals.start()].strip().splitlines()[:nvar]:
        parts = line.split()
        names.append(parts[1].lower())
    nums = text[m_vals.end() :].split()
    # Each point: index, then nvar values.
    data = np.empty((npts, nvar))
    k = 0
    for p in range(npts):
        k += 1  # point index
        for v in range(nvar):
            data[p, v] = float(nums[k].split(",")[0])
            k += 1
    return Plot(m_name.group(1).strip() if m_name else "", {n: data[:, i] for i, n in enumerate(names)})


# Fallback integrator settings tried when a transient aborts with "timestep too small"
# (typical for hard-switching circuits); results of a successful retry are equally valid.
RETRY_OPTIONS = (
    "",
    ".options method=gear",
    ".options method=gear reltol=0.003 chgtol=1e-12",
    # last resort: 1 pF from every node to ground (electrically negligible here) damps
    # the numerically stiff switch-node edges that otherwise abort the transient
    ".options cshunt=1e-12",
    # 10 pF still is negligible next to the timing/gate capacitances of the converters here
    ".options cshunt=1e-11",
)


def _with_options(deck_text: str, extra: str) -> str:
    lines = deck_text.splitlines()
    for i, ln in enumerate(lines):
        if ln.lower().startswith(".options"):
            lines.insert(i + 1, extra)
            break
    return "\n".join(lines) + "\n"


def _run_once(deck_text: str, workdir: Path, timeout: int, exe: str) -> tuple[dict[str, Plot], str]:
    (workdir / "deck.cir").write_text(deck_text)
    for f in ("op.raw", "tran.raw"):
        (workdir / f).unlink(missing_ok=True)
    m = re.search(r"^\* cloop-compat: (\w+)", deck_text, re.M)
    env = None
    cmd = [exe, "-b", "-n", "deck.cir"]  # -n: ignore any user .spiceinit
    if m:
        # Compatibility modes can only be set from .spiceinit; ngspice reads it from the working
        # directory. HOME points at the run directory so a personal ~/.spiceinit cannot leak in.
        (workdir / ".spiceinit").write_text(f"set ngbehavior={m.group(1)}\n")
        env = dict(os.environ, HOME=str(workdir))
        cmd = [exe, "-b", "deck.cir"]
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise SimError(f"ngspice timed out after {timeout}s") from e
    except OSError as e:
        raise NgspiceUnavailable(f"ngspice cannot be started: {e}") from e
    log = proc.stdout + proc.stderr
    (workdir / "ngspice.log").write_text(log)
    m_broken = _BROKEN.search(log)
    if proc.returncode in (126, 127) or m_broken:
        line = next((ln for ln in log.splitlines() if _BROKEN.search(ln)), log.strip()[:300])
        raise NgspiceUnavailable(f"ngspice cannot run on this system: {line.strip()}")
    plots: dict[str, Plot] = {}
    for key in ("op", "tran"):
        f = workdir / f"{key}.raw"
        if f.is_file() and f.stat().st_size > 0:
            plots[key] = parse_raw(f)
    return plots, log


def smoke_test(timeout: int = 60) -> str | None:
    """Run a trivial deck. None if ngspice works, otherwise what is wrong (for doctor / Phase 0)."""
    import tempfile

    deck = "* cloop smoke test\nV1 a 0 1\nR1 a 0 1k\n.control\nop\nprint v(a)\n.endc\n.end\n"
    exe = shutil.which("ngspice")
    if exe is None:
        return "ngspice not found in PATH"
    with tempfile.TemporaryDirectory(prefix="cloop-smoke-") as d:
        try:
            _run_once(deck, Path(d), timeout, exe)
        except SimError as e:
            return str(e)
        log = (Path(d) / "ngspice.log").read_text()
    if not re.search(r"v\(a\)\s*=\s*1", log, re.I):
        return "ngspice ran but did not produce a result: " + (log.strip()[-300:] or "(no output)")
    return None


def run_ngspice(deck_text: str, workdir: Path, timeout: int = 300) -> SimResult:
    exe = shutil.which("ngspice")
    if exe is None:
        raise SimError("ngspice not found in PATH (run `cloop doctor`)")
    workdir.mkdir(parents=True, exist_ok=True)
    wants_tran = re.search(r"^tran ", deck_text, re.M) is not None
    retries = 0
    for i, extra in enumerate(RETRY_OPTIONS):
        retries = i
        text = _with_options(deck_text, extra) if extra else deck_text
        plots, log = _run_once(text, workdir, timeout, exe)
        if not wants_tran or "tran" in plots or "timestep too small" not in log.lower():
            break
    if "op" not in plots and "tran" not in plots:
        errs = [ln for ln in log.splitlines() if re.search(r"error|singular|converge|fatal", ln, re.I)]
        raise SimError("ngspice failed: " + ("; ".join(errs[:8]) or log.strip()[-500:]))
    tran_error = None
    if wants_tran and "tran" not in plots:
        errs = [ln.strip() for ln in log.splitlines() if re.search(r"too small|abort|error", ln, re.I)]
        tran_error = "; ".join(errs[:3]) or "no transient data"
    # ngspice falls back to a pseudo-transient ("Transient op") when the DC
    # operating point does not converge; that snapshot is not a valid op.
    return SimResult(
        plots,
        op_converged="op" in plots and "Transient op started" not in log,
        tran_error=tran_error,
        retries=retries,
    )
