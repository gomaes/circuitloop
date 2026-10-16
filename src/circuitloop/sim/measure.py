"""Deterministic measurements on simulation results.

Steady state is defined as:
- the transient window ``t >= spec.transient.settle`` when the spec has a
  transient section (power-on start-up is excluded), otherwise
- the DC operating point, which must have converged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..netlist import Netlist
from ..partsdb import PartsDB, Rating
from ..spec import DcVoltage, Frequency, Gain, InputCurrent, InputPower, Ripple, Spec
from .ngspice import SimResult
from .spice import SRC, ammeter, node_name, pin_node


class Waveforms:
    def __init__(self, sim: SimResult, spec: Spec):
        self.sim = sim
        self.spec = spec
        self.mode = "tran" if (spec.transient is not None and "tran" in sim.plots) else "op"
        self.valid = self.mode == "tran" or (spec.transient is None and sim.op_converged)
        plot = sim.plots.get(self.mode)
        if self.mode == "tran":
            self._mask = plot.time >= spec.transient.settle
            self.t = plot.time[self._mask]
        else:
            self._mask = np.ones(1, dtype=bool)
            self.t = None
        self._plot = plot

    @property
    def invalid_reason(self) -> str:
        if self.spec.transient is not None and "tran" not in self.sim.plots:
            return f"transient analysis aborted ({self.sim.tran_error or 'no data'})"
        return "DC operating point did not converge"

    @property
    def plots(self):
        return self.sim.plots

    def _raw(self, key: str) -> np.ndarray | None:
        if self._plot is None:
            return None
        if key == "v(0)":
            return np.zeros(len(self._mask))
        return self._plot.get(key)

    def _steady(self, key: str) -> np.ndarray | None:
        x = self._raw(key)
        return None if x is None else np.asarray(x)[self._mask]

    def v_net(self, net: str) -> np.ndarray | None:
        return self._steady(f"v({node_name(net, self.spec.ground_net)})")

    def v_node(self, node: str) -> np.ndarray | None:
        return self._steady(f"v({node})")

    def i(self, source: str) -> np.ndarray | None:
        return self._steady(f"i({source.lower()})")

    def mean(self, x: np.ndarray) -> float:
        if self.t is None or len(x) < 2 or self.t[-1] <= self.t[0]:
            return float(np.mean(x))
        return float(np.trapezoid(x, self.t) / (self.t[-1] - self.t[0]))

    def full_tran(self, net: str) -> tuple[np.ndarray, np.ndarray] | None:
        plot = self.sim.plots.get("tran")
        if plot is None:
            return None
        v = plot.get(f"v({node_name(net, self.spec.ground_net)})")
        if v is None and net == self.spec.ground_net:
            v = np.zeros(len(plot.time))
        return (plot.time, v) if v is not None else None


@dataclass
class Measured:
    id: str
    value: float | None
    limit: str
    passed: bool
    detail: str = ""


def _limit(lo: float | None, hi: float | None, unit: str) -> str:
    if lo is not None and hi is not None:
        return f"{lo:g}..{hi:g} {unit}"
    if hi is not None:
        return f"<= {hi:g} {unit}"
    return f">= {lo:g} {unit}"


def _in(v: float | None, lo: float | None, hi: float | None) -> bool:
    if v is None or not np.isfinite(v):
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def frequency_of(t: np.ndarray, x: np.ndarray) -> float | None:
    if len(x) < 3 or np.ptp(x) < 1e-3:
        return None
    thr = (np.max(x) + np.min(x)) / 2
    above = x >= thr
    idx = np.where(~above[:-1] & above[1:])[0]
    if len(idx) < 2:
        return None
    tc = t[idx] + (thr - x[idx]) * (t[idx + 1] - t[idx]) / (x[idx + 1] - x[idx])
    return float((len(tc) - 1) / (tc[-1] - tc[0]))


def input_power(wf: Waveforms) -> float | None:
    i = wf.i(SRC)
    v = wf.v_net(wf.spec.power_input.pos_net)
    if i is None or v is None:
        return None
    return wf.mean(-i * v)


def measure_criterion(c, wf: Waveforms) -> Measured:
    key = c.key()
    if not wf.valid:
        return Measured(key, None, "", False, wf.invalid_reason)
    if isinstance(c, DcVoltage):
        v = wf.v_net(c.net)
        val = wf.mean(v) if v is not None else None
        return Measured(
            key,
            val,
            _limit(c.min, c.max, "V"),
            _in(val, c.min, c.max),
            "" if v is not None else f"net {c.net} not found",
        )
    if isinstance(c, InputCurrent):
        i = wf.i(SRC)
        val = wf.mean(-i) if i is not None else None
        return Measured(key, val, _limit(None, c.max, "A"), _in(val, None, c.max))
    if isinstance(c, InputPower):
        val = input_power(wf)
        return Measured(key, val, _limit(None, c.max, "W"), _in(val, None, c.max))
    if wf.mode != "tran":
        return Measured(key, None, "", False, "no transient data")
    if isinstance(c, Ripple):
        x = wf.v_net(c.net)
        val = float(np.ptp(x)) if x is not None else None
        return Measured(key, val, _limit(None, c.max, "Vpp"), _in(val, None, c.max))
    if isinstance(c, Frequency):
        x = wf.v_net(c.net)
        val = frequency_of(wf.t, x) if x is not None else None
        return Measured(
            key,
            val,
            _limit(c.min, c.max, "Hz"),
            _in(val, c.min, c.max),
            "" if val is not None else "no oscillation detected in the measurement window",
        )
    if isinstance(c, Gain):
        xi, xo = wf.v_net(c.input_net), wf.v_net(c.output_net)
        if xi is None or xo is None or np.ptp(xi) < 1e-9:
            return Measured(key, None, _limit(c.min, c.max, "V/V"), False, "input has no signal")
        val = float(np.ptp(xo) / np.ptp(xi))
        return Measured(key, val, _limit(c.min, c.max, "V/V"), _in(val, c.min, c.max))
    raise TypeError(c)


@dataclass
class RatingCheck:
    ref: str
    part: str
    rating: str
    peak: float
    limit_lo: float | None
    limit_hi: float
    passed: bool

    @property
    def utilization(self) -> float:
        lim = self.limit_hi if self.peak >= 0 or self.limit_lo is None else abs(self.limit_lo)
        return abs(self.peak) / lim if lim else float("inf")


def check_ratings(
    nl: Netlist, db: PartsDB, refs: list[str], wf: Waveforms, factors: dict[str, float]
) -> list[RatingCheck]:
    out: list[RatingCheck] = []
    for ref in refs:
        pd = db[nl.components[ref].part_key]
        for r in pd.ratings:
            rc = _check_one(ref, pd, r, wf, factors)
            if rc is not None:
                out.append(rc)
    return out


def _extreme(x: np.ndarray, lo: float, hi: float, tol: float) -> tuple[float, bool]:
    """Return (reported value, passed): the worst violating sample, else the largest magnitude."""
    if np.max(x) > hi + tol:
        return float(np.max(x)), False
    if np.min(x) < lo - tol:
        return float(np.min(x)), False
    return float(x[np.argmax(np.abs(x))]), True


def _check_one(ref: str, pd, r: Rating, wf: Waveforms, factors: dict[str, float]) -> RatingCheck | None:
    f = factors[r.type]
    if r.type == "voltage":
        a, b = r.pins
        va, vb = wf.v_node(pin_node(ref, a)), wf.v_node(pin_node(ref, b))
        if va is None or vb is None:
            return None
        x = va - vb
        lo, hi = r.lower * f, r.max * f
        peak, ok = _extreme(x, lo, hi, 1e-9)
        return RatingCheck(ref, pd.key, f"voltage V({a},{b})", peak, lo, hi, ok)
    if r.type == "current":
        x = wf.i(ammeter(ref, r.pin))
        if x is None:
            return None
        lo, hi = r.lower * f, r.max * f
        if r.mode == "average":
            x = np.array([wf.mean(x)])
        elif r.mode == "rms":
            x = np.array([math.sqrt(max(wf.mean(x * x), 0.0))])
            lo = 0.0
        peak, ok = _extreme(x, lo, hi, 1e-12)
        label = f"current I(pin {r.pin})" + ("" if r.mode == "peak" else f" {r.mode}")
        return RatingCheck(ref, pd.key, label, peak, lo, hi, ok)
    total = None
    for num in pd.pins:
        v, i = wf.v_node(pin_node(ref, num)), wf.i(ammeter(ref, num))
        if v is None or i is None:
            continue
        total = v * i if total is None else total + v * i
    if total is None:
        return None
    # power ratings are thermal: compare the average dissipation over the steady-state window
    hi = r.max * f
    avg = wf.mean(total)
    return RatingCheck(ref, pd.key, "power (average)", avg, None, hi, bool(avg <= hi + 1e-12))
