"""Run independent ngspice simulations concurrently.

Each ngspice process is single-threaded and small (~30 MB for the bundled
examples), so the useful degree of parallelism is bounded by the CPUs this
process may use and by the number of independent scenarios (supply corners +
fault cases) in one verification.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .ngspice import NgspiceUnavailable, SimError, SimResult, run_ngspice

# Rough upper bound of memory per simulation incl. parsing its raw file in Python.
MEM_PER_JOB = 300 * 1024 * 1024


def available_cpus() -> int:
    """CPUs usable by this process: affinity mask and cgroup (v2 or v1) CPU quota."""
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    quota = None
    try:
        q, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if q != "max":
            quota = int(q) / int(period)
    except (OSError, ValueError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if q > 0:
                quota = q / period
        except (OSError, ValueError):
            pass
    if quota is not None:
        n = min(n, max(1, int(quota)))
    return max(1, n)


def available_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def auto_jobs(n_tasks: int, requested: int | None = None) -> int:
    """Number of parallel simulations: requested value, else min(CPUs, tasks, memory budget)."""
    if requested is not None and requested > 0:
        return max(1, min(requested, n_tasks))
    n = min(available_cpus(), n_tasks)
    mem = available_memory()
    if mem is not None:
        n = min(n, max(1, mem // MEM_PER_JOB))
    return max(1, n)


@dataclass
class SimJob:
    deck_text: str
    workdir: Path
    timeout: int


def run_jobs(jobs: list[SimJob], max_workers: int) -> dict[Path, SimResult | SimError]:
    def one(job: SimJob) -> SimResult | SimError:
        try:
            return run_ngspice(job.deck_text, job.workdir, job.timeout)
        except SimError as e:
            return e

    if max_workers <= 1 or len(jobs) <= 1:
        out = {j.workdir: one(j) for j in jobs}
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:  # ngspice runs out-of-process
            results = list(ex.map(one, jobs))
        out = {j.workdir: r for j, r in zip(jobs, results, strict=True)}
    broken = next((r for r in out.values() if isinstance(r, NgspiceUnavailable)), None)
    if broken is not None:  # nothing about the design can be concluded: stop instead of reporting it
        raise broken
    return out


SimFn = Callable[[str, Path, int], SimResult]


def cached_sim_fn(results: dict[Path, SimResult | SimError]) -> SimFn:
    """A drop-in for run_ngspice that returns precomputed results (falls back to running)."""

    def fn(deck_text: str, workdir: Path, timeout: int) -> SimResult:
        r = results.get(workdir)
        if r is None:
            return run_ngspice(deck_text, workdir, timeout)
        if isinstance(r, SimError):
            raise r
        return r

    return fn
