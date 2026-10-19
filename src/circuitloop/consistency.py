"""Contradictions inside the fault expectations of a spec, found without designing anything.

During a fault the simulation harness applies the (reversed or raised) supply, attaches every load
as a fixed resistor (constant-current loads by their resistive equivalent) and keeps the stimuli
connected. The board itself is passive, so by conservation of energy the supply has to deliver at
least the power the loads are forced to dissipate, minus what the stimuli can deliver:

    |Vfault| x I_supply >= sum over loads of d_min^2 / R - sum over stimuli of Vpeak^2 / (4 Rs)

where d_min is the smallest voltage across a load that the fault's own net limits allow (ground is
0 V, the supply net sits at the fault voltage within the source-resistance drop). When that
required current exceeds `max_input_current`, no design can pass the fault: the limits contradict
each other. Limits that cannot hold at all (an empty range, ground outside its range, the supply
net outside the range the fault forces on it) are reported too. Each problem names the smallest
change that removes it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .spec import Fault, Spec

INF = math.inf


@dataclass
class Conflict:
    fault: str
    message: str

    def __str__(self) -> str:
        return f"fault '{self.fault}': {self.message}"


def _load_resistance(spec: Spec, load) -> float:
    from .sim.spice import _load_resistance as r

    return r(spec, load)


def _gap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Smallest |x - y| for x in a, y in b."""
    return max(0.0, a[0] - b[1], b[0] - a[1])


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def fault_conflicts(spec: Spec) -> list[Conflict]:
    out: list[Conflict] = []
    for f in spec.effective_faults():
        out += _check(spec, f)
    return out


def _check(spec: Spec, f: Fault) -> list[Conflict]:
    pi = spec.power_input
    v = f.voltage if f.voltage is not None else pi.v_nom
    vs = -abs(v) if f.kind == "reverse_polarity" else v
    imax = f.expect.max_input_current
    out: list[Conflict] = []
    # where the fault puts the supply net: the source voltage minus at most Imax x Rs
    drop = imax * pi.source_resistance if imax is not None else INF
    forced = {pi.pos_net: (vs - drop, vs + drop), spec.ground_net: (0.0, 0.0)}
    limits: dict[str, tuple[float, float]] = {}
    for net, lim in f.expect.nets.items():
        lo = -INF if lim.min is None else lim.min
        hi = INF if lim.max is None else lim.max
        if lo > hi:
            out.append(Conflict(f.name, f"net {net}: min {lo:g} V is above max {hi:g} V"))
            continue
        if net in forced and _gap((lo, hi), forced[net]) > 1e-9:
            flo, fhi = forced[net]
            what = "ground (0 V)" if net == spec.ground_net else f"the supply net at {_fmt(vs)} V"
            out.append(
                Conflict(
                    f.name,
                    f"net {net} must stay within {lo:g}..{hi:g} V, but it is {what}"
                    + (
                        ""
                        if net == spec.ground_net
                        else f" (within the source-resistance drop: {_fmt(flo)}..{_fmt(fhi)} V)"
                    )
                    + f". Remove this limit or include {_fmt(flo if lo > fhi else fhi)} V in it.",
                )
            )
            continue
        limits[net] = (lo, hi)
    if imax is None:
        return out
    ranges = {**limits, **forced}  # forced voltages are exact (within the drop)
    loads = []
    for ld in spec.loads:
        a, b = ld.net, ld.ref_net or spec.ground_net
        ra, rb = ranges.get(a, (-INF, INF)), ranges.get(b, (-INF, INF))
        r = _load_resistance(spec, ld)
        d = _gap(ra, rb)
        loads.append((ld, a, b, r, d, d * d / r))
    p_loads = sum(x[5] for x in loads)
    p_stim = 0.0
    for st in spec.stimuli:
        vpk = abs(st.dc) + abs(st.amplitude)
        p_stim += INF if st.source_resistance <= 0 else vpk * vpk / (4 * st.source_resistance)
    p_need = p_loads - p_stim
    if p_need <= 0 or abs(vs) <= 0:
        return out
    i_need = p_need / abs(vs)
    if i_need <= imax * (1 + 1e-9):
        return out
    # explain with the load(s) that force the power, and the smallest fix on each side
    main = max(loads, key=lambda x: x[5])
    ld, a, b, r, d, p = main
    p_allow = imax * abs(vs) + p_stim - (p_loads - p)
    lim_net = a if a in limits else b if b in limits else None
    fix_net = ""
    if lim_net is not None and p_allow > 0:
        other = b if lim_net == a else a
        lo, hi = limits[lim_net]
        olo, ohi = ranges.get(other, (-INF, INF))
        d_allow = math.sqrt(p_allow * r)
        if lo > ohi:  # the limited net is held above the other end of the load
            fix_net = f"let {lim_net} go down to {_fmt(ohi + d_allow)} V (its min is {lo:g} V)"
        elif hi < olo:
            fix_net = f"let {lim_net} go up to {_fmt(olo - d_allow)} V (its max is {hi:g} V)"
    elif lim_net is not None:
        fix_net = f"remove the limit on {lim_net}"
    span = f"{ranges[a][0]:g}..{ranges[a][1]:g} V" if a in ranges else "unconstrained"
    msg = (
        f"the expectations contradict each other. With the supply at {_fmt(vs)} V, the load on {a} "
        f"({_fmt(r)} Ohm to {b}) is attached by the harness, and keeping {a} within {span} puts at "
        f"least {_fmt(d)} V across it, i.e. {_fmt(p)} W"
        + (f" ({_fmt(p_loads)} W in all loads)" if len(loads) > 1 else "")
        + (f", minus up to {_fmt(p_stim)} W the stimuli can deliver" if p_stim > 0 else "")
        + f". The board is passive, so the supply must deliver at least {_fmt(p_need)} W / "
        f"{_fmt(abs(vs))} V = {_fmt(i_need)} A, but max_input_current is {imax:g} A. "
        f"Smallest fixes: raise max_input_current to >= {_fmt(i_need)} A"
        + (f", or {fix_net}" if fix_net else "")
        + "."
    )
    out.append(Conflict(f.name, msg))
    return out
