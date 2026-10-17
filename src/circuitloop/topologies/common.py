"""Spec-derived targets, part selection against derated ratings, shared building blocks."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ..partsdb import PartDef, PartsDB, Rating
from ..spec import DcVoltage, Spec
from ..units import fmt_si
from .eseries import E6, ceil_to, fmt_value
from .writer import DesignWriter, TopologyError


@dataclass
class Ctx:
    spec: Spec
    db: PartsDB
    params: dict[str, str]
    protect: bool  # include the protection required by spec.protection
    notes: list[str] = field(default_factory=list)

    # ---- parameters -----------------------------------------------------
    def param(self, name: str, default, conv: Callable = str):
        raw = self.params.get(name)
        if raw is None or raw == "auto":
            return default
        try:
            return conv(raw)
        except ValueError as e:
            raise TopologyError(f"parameter {name}={raw!r}: {e}") from e

    def note(self, text: str) -> None:
        self.notes.append(text)

    # ---- spec helpers ---------------------------------------------------
    @property
    def der_v(self) -> float:
        return self.spec.derating.voltage

    @property
    def der_i(self) -> float:
        return self.spec.derating.current

    @property
    def der_p(self) -> float:
        return self.spec.derating.power

    @property
    def v_abs(self) -> float:
        """Highest input voltage the board must survive (normal operation or overvoltage faults)."""
        vs = [self.spec.power_input.v_max] + [
            f.voltage for f in self.spec.effective_faults() if f.kind == "overvoltage" and f.voltage
        ]
        return max(vs)

    @property
    def v_reverse(self) -> float:
        """Largest reversed supply voltage of the reverse-polarity faults (0 if none)."""
        vs = [
            f.voltage if f.voltage is not None else self.spec.power_input.v_nom
            for f in self.spec.effective_faults()
            if f.kind == "reverse_polarity"
        ]
        return max(vs, default=0.0)

    def wants(self, protection: str) -> bool:
        return self.protect and protection in self.spec.protection

    def load_current(self, net: str, v: float) -> float:
        total = 0.0
        for ld in self.spec.loads:
            if ld.net == net:
                total += ld.current if ld.current is not None else v / ld.resistance
        return total

    def dc_target(self, pred: Callable[[DcVoltage], bool] = lambda c: True) -> DcVoltage | None:
        for c in self.spec.acceptance:
            if isinstance(c, DcVoltage) and c.net != self.spec.power_input.pos_net and pred(c):
                return c
        return None

    def criterion(self, cls):
        return next((c for c in self.spec.acceptance if isinstance(c, cls)), None)

    # ---- part selection -------------------------------------------------
    def part(self, key: str) -> PartDef:
        if key not in self.db:
            raise TopologyError(f"part '{key}' is not in the parts DB")
        return self.db[key]

    def of_kind(self, *kinds: str) -> list[PartDef]:
        return [self.db[k] for k in self.db.keys() if self.db[k].kind in kinds]


def ratings(pd: PartDef, typ: str, mode: str | None = None) -> list[Rating]:
    return [r for r in pd.ratings if r.type == typ and (mode is None or r.mode == mode)]


def rating_max(pd: PartDef, typ: str, mode: str | None = None) -> float | None:
    rs = ratings(pd, typ, mode)
    return min((r.max for r in rs), default=None)


def value_fits(pd: PartDef, value: float) -> bool:
    return (pd.value_min is None or value >= pd.value_min * (1 - 1e-9)) and (
        pd.value_max is None or value <= pd.value_max * (1 + 1e-9)
    )


def check_current(pd: PartDef, cx: Ctx, peak: float = 0.0, avg: float = 0.0, rms: float = 0.0) -> str | None:
    """None if every current rating of the part covers the stress after derating."""
    stress = {"peak": peak, "average": avg, "rms": rms}
    for r in ratings(pd, "current"):
        need = stress[r.mode] if r.mode != "peak" else max(peak, rms, avg)
        if need > r.max * cx.der_i + 1e-12:
            return f"{r.mode} current {fmt_si(need, 'A')} > {fmt_si(r.max * cx.der_i, 'A')} (derated)"
    return None


def check_voltage(pd: PartDef, cx: Ctx, work: float, absolute: float | None = None) -> str | None:
    for r in ratings(pd, "voltage"):
        if work > r.max * cx.der_v + 1e-12:
            return f"voltage {work:.3g} V > {r.max * cx.der_v:.3g} V (derated)"
        if absolute is not None and absolute > r.max + 1e-12:
            return f"fault voltage {absolute:.3g} V > absolute maximum {r.max:g} V"
    return None


def check_power(pd: PartDef, cx: Ctx, power: float) -> str | None:
    pmax = rating_max(pd, "power")
    if pmax is not None and power > pmax * cx.der_p + 1e-12:
        return f"dissipation {fmt_si(power, 'W')} > {fmt_si(pmax * cx.der_p, 'W')} (derated)"
    return None


def choose(cands: list[PartDef], check: Callable[[PartDef], str | None], what: str, key=None) -> PartDef:
    """First candidate (after sorting by `key`) that passes `check`; otherwise explain every rejection."""
    reasons = []
    for pd in sorted(cands, key=key) if key else cands:
        why = check(pd)
        if why is None:
            return pd
        reasons.append(f"{pd.key}: {why}")
    raise TopologyError(
        f"no registered part can serve as {what}"
        + (": " + "; ".join(reasons) if reasons else " (none of that kind registered)")
        + ". Register a suitable part (`cloop parts add`) or relax the spec."
    )


def pick_resistor(
    cx: Ctx, value: float, power: float, voltage: float = 0.0, what: str = "resistor"
) -> PartDef:
    def ok(pd: PartDef) -> str | None:
        if not value_fits(pd, value):
            return "value out of range"
        return check_power(pd, cx, power) or check_voltage(pd, cx, voltage)

    return choose(
        cx.of_kind("resistor"), ok, what, key=lambda p: (p.tolerance or 1, rating_max(p, "power") or 0)
    )


def pick_capacitor(
    cx: Ctx,
    value: float,
    v_work: float,
    v_abs: float | None = None,
    kinds: tuple[str, ...] = ("capacitor", "electrolytic"),
    i_rms: float = 0.0,
    what: str = "capacitor",
    prefer: str = "ceramic",
) -> PartDef:
    """prefer: 'ceramic' (decoupling), 'precise' (timing: tightest tolerance), 'low_esr' (power)."""

    def ok(pd: PartDef) -> str | None:
        if not value_fits(pd, value):
            return f"{fmt_si(value, 'F')} outside its value range"
        return check_voltage(pd, cx, v_work, v_abs) or (check_current(pd, cx, rms=i_rms) if i_rms else None)

    def order(pd: PartDef):
        vmax = rating_max(pd, "voltage") or 0
        if prefer == "precise":  # timing: tight tolerance, stable film dielectric
            return (pd.tolerance or 1, "film" not in pd.description.lower(), vmax)
        if prefer == "low_esr":
            return (pd.design.get("esr", 0 if pd.kind == "capacitor" else 1), vmax)
        return (pd.kind != "capacitor", "FILM" in pd.key, vmax)

    return choose(cx.of_kind(*kinds), ok, what, key=order)


def place_cap(
    w: DesignWriter, cx: Ctx, value: float, a: str, b: str, v_work: float, comment: str, **kw
) -> str:
    """Place a capacitor between nets a (+) and b; returns its ref."""
    pd = pick_capacitor(cx, value, v_work, cx.v_abs, what=comment, **kw)
    ref = w.add(pd.key, fmt_value(value), comment)
    if pd.kind == "electrolytic":
        w.connect(a, f"{ref}.POS")
        w.connect(b, f"{ref}.NEG")
    else:
        w.connect(a, f"{ref}.1")
        w.connect(b, f"{ref}.2")
    return ref


def decoupling(w: DesignWriter, cx: Ctx, ref: str, pin_net: dict[int, str], v_work: float) -> None:
    """Capacitors required by the part's `decoupling` entries (ceramic up to 1 uF, else electrolytic)."""
    pd = cx.db[w.key_of(ref)]
    for d in pd.decoupling:
        a, b = pin_net[d.pin], pin_net[d.gnd]
        pin = pd.pins[d.pin].name
        if d.min >= 1e-6:
            c = ceil_to(2 * d.min, E6)
            place_cap(
                w,
                cx,
                c,
                a,
                b,
                v_work,
                f"{ref} {pin} stability cap (>= {fmt_si(d.min, 'F')})",
                kinds=("electrolytic",),
            )
            place_cap(w, cx, 100e-9, a, b, v_work, f"{ref} {pin} HF decoupling")
        else:
            c = ceil_to(max(d.min, 100e-9), E6)
            place_cap(w, cx, c, a, b, v_work, f"{ref} {pin} decoupling (>= {fmt_si(d.min, 'F')})")


def connector(w: DesignWriter, pins: int, comment: str, power: bool) -> str:
    key = "TERM_2P_5.08" if power and pins == 2 else f"HDR_1x{pins:02d}"
    return w.add(key, comment=comment)


@dataclass
class FrontEnd:
    rail: str  # net that feeds the circuit
    drop: Callable[[float], float]  # series voltage drop at input current i (protection parts + source)
    parts: list[str] = field(default_factory=list)


def supply_front_end(
    w: DesignWriter,
    cx: Ctx,
    i_in: float,
    rail: str,
    power_connector: bool,
    i_peak: float | None = None,
    bulk: float | None = None,
) -> FrontEnd:
    """Input connector + protection required by the spec (PTC for overcurrent, series Schottky for
    reverse polarity) + optional bulk capacitor after the protection. Returns the protected rail."""
    sp = cx.spec
    pos, gnd = sp.power_input.pos_net, sp.ground_net
    j = connector(w, 2, f"supply input ({pos} / {gnd})", power_connector)
    w.connect(pos, f"{j}.1")
    w.connect(gnd, f"{j}.2")
    i_peak = i_peak if i_peak is not None else i_in
    src_r = sp.power_input.source_resistance
    chain: list[tuple[str, float, float]] = []  # (ref, series R, forward drop)
    net = pos
    if cx.wants("overcurrent"):
        ptc = choose(
            cx.of_kind("ptc", "fuse"),
            lambda pd: (
                check_current(pd, cx, peak=1.2 * i_in, avg=1.2 * i_in, rms=1.2 * i_in)
                or check_voltage(pd, cx, 0.0, cx.v_abs)
            ),
            f"overcurrent protection for {fmt_si(i_in, 'A')}",
            key=lambda p: rating_max(p, "current") or 0,
        )
        hold = rating_max(ptc, "current") or 0
        f = w.add(
            ptc.key,
            comment=f"overcurrent: hold {hold:g} A x derating {cx.der_i:g} >= 1.2 x {fmt_si(i_in, 'A')}",
        )
        nxt = rail if not cx.wants("reverse_polarity") else f"{pos}_F"
        w.connect(net, f"{f}.1")
        w.connect(nxt, f"{f}.2")
        chain.append((f, ptc.design.get("r", 0.0), 0.0))
        cx.note(
            f"{f} {ptc.key}: PTC sized for input current {fmt_si(i_in, 'A')} (typ. {ptc.design.get('r', 0):g} ohm)"
        )
        net = nxt
    if cx.wants("reverse_polarity"):
        v_rev = max(cx.v_reverse, sp.power_input.v_max)

        def ok(pd: PartDef) -> str | None:
            if "vf" not in pd.design:
                return "no forward-voltage figure (design.vf)"
            # forward in normal operation; reverse voltage only under the fault (absolute maximum)
            return (
                check_current(pd, cx, peak=i_peak, avg=i_in, rms=i_in)
                or check_power(pd, cx, 1.2 * pd.design["vf"] * i_in)
                or _reverse_ok(pd, v_rev)
            )

        dpd = choose(
            cx.of_kind("diode"),
            ok,
            f"reverse-polarity diode for {fmt_si(i_in, 'A')}",
            key=lambda p: (p.design.get("vf", 9), rating_max(p, "current") or 0),
        )
        d = w.add(dpd.key, comment=f"reverse polarity: series diode (Vf ~{dpd.design['vf']:g} V)")
        w.connect(net, f"{d}.A")
        w.connect(rail, f"{d}.K")
        chain.append((d, 0.0, dpd.design["vf"]))
        cx.note(
            f"{d} {dpd.key}: series reverse-polarity diode, Vf ~{dpd.design['vf']:g} V, reverse >= {v_rev:g} V"
        )
    if bulk:
        v_work = sp.power_input.v_max
        place_cap(
            w, cx, bulk, rail, gnd, v_work, "bulk input capacitor", kinds=("electrolytic",), prefer="low_esr"
        )
    r_series = src_r + sum(r for _, r, _ in chain)
    vf = sum(v for _, _, v in chain)
    return FrontEnd(rail, lambda i: i * r_series + (vf if i > 0 else 0.0), [r for r, _, _ in chain])


def _reverse_ok(pd: PartDef, v_rev: float) -> str | None:
    for r in ratings(pd, "voltage"):
        # diode voltage ratings are V(K, A): max = reverse blocking voltage
        if r.max < v_rev:
            return f"reverse voltage {r.max:g} V < {v_rev:g} V"
    return None


def fmt(x: float, unit: str) -> str:
    return fmt_si(x, unit) if math.isfinite(x) else str(x)
