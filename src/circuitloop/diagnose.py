"""Deterministic root-cause diagnosis of a failed verification.

Each diagnoser reads the netlist, the part design data (``design:`` in the parts DB), the spec and the
gate results, recomputes the textbook quantity behind a failure (555 frequency, op-amp gain, divider
set-point, current limit, gate turn-off time, ESR ripple, regulator headroom, ...) and states the
cause together with a concrete change. The output is advice for the fixing agent only: it never
affects pass/fail, which the gates alone decide.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np

from .netlist import Netlist
from .partsdb import PartDef, PartsDB
from .report import VerificationReport
from .sim.spice import SRC
from .spec import DcVoltage, Frequency, Gain, Ripple, Spec
from .topologies.eseries import E12, E24_E96, ceil_to, floor_to, fmt_value, nearest
from .units import fmt_si, parse_value


@dataclass
class Diagnosis:
    topic: str
    cause: str
    fix: str
    refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Circuit:
    """Netlist view with part data and simulation results for the diagnosers."""

    def __init__(self, nl: Netlist, db: PartsDB, spec: Spec, report: VerificationReport, sim=None):
        self.nl, self.db, self.spec, self.report, self.sim = nl, db, spec, report, sim
        self.gnd = spec.ground_net

    # ---- netlist --------------------------------------------------------
    def pd(self, ref: str) -> PartDef | None:
        c = self.nl.components.get(ref)
        return self.db.get(c.part_key) if c else None

    def refs(self, *kinds: str, key: str | None = None) -> list[str]:
        out = []
        for ref in sorted(self.nl.components):
            pd = self.pd(ref)
            if pd is not None and (pd.kind in kinds or (key is not None and pd.key == key)):
                out.append(ref)
        return out

    def net(self, ref: str, pin_name: str) -> str | None:
        pd = self.pd(ref)
        num = pd.pin_by_name(pin_name) if pd else None
        return self.nl.net_of(ref, num) if num is not None else None

    def nets(self, ref: str) -> set[str]:
        return {n for (r, _), n in self.nl.pin_net.items() if r == ref}

    def between(self, a: str, b: str, *kinds: str) -> list[str]:
        """Two-pin parts of the given kinds connected between nets a and b."""
        return [r for r in self.refs(*kinds) if self.nets(r) == {a, b}]

    def value(self, ref: str) -> float | None:
        try:
            return parse_value(self.nl.components[ref].value)
        except (ValueError, KeyError):
            return None

    def total_c(self, a: str, b: str) -> float:
        return sum(self.value(r) or 0 for r in self.between(a, b, "capacitor", "electrolytic"))

    def resistor(self, a: str, b: str) -> tuple[str, float] | None:
        rs = [(r, self.value(r)) for r in self.between(a, b, "resistor")]
        rs = [(r, v) for r, v in rs if v]
        if not rs:
            return None
        g = sum(1 / v for _, v in rs)
        return ",".join(r for r, _ in rs), 1 / g

    def resistors_from(self, net: str, exclude: set[str] = frozenset()) -> list[tuple[str, str, float]]:
        out = []
        for r in self.refs("resistor"):
            ns = self.nets(r)
            if net in ns and len(ns) == 2:
                other = next(iter(ns - {net}))
                v = self.value(r)
                if other not in exclude and v:
                    out.append((r, other, v))
        return out

    # ---- results --------------------------------------------------------
    def failed_rows(self) -> list[dict]:
        rows = []
        for g in self.report.gates:
            rows += [c for c in g.metrics.get("criteria", []) if not c.get("passed", True)]
        return rows

    def failed(self, cid: str) -> bool:
        if any(r["id"] == cid for r in self.failed_rows()):
            return True
        return any(
            f"{cid} =" in f.message or f"] {cid}:" in f.message for g in self.report.gates for f in g.errors()
        )

    def findings(self, pattern: str) -> list:
        rx = re.compile(pattern)
        return [f for g in self.report.gates for f in g.errors() if rx.search(f.rule)]

    def rating_failures(self, ref: str) -> list:
        return [f for f in self.findings(r"^ratings\.") if ref in f.refs]

    def waveforms(self) -> dict:
        return getattr(self.sim, "waveforms", {}) if self.sim is not None else {}

    def v_net(self, scenario: str, net: str) -> np.ndarray | None:
        wf = self.waveforms().get(scenario)
        return None if wf is None else wf.v_net(net)

    def i_in(self, scenario: str) -> float | None:
        wf = self.waveforms().get(scenario)
        i = wf.i(SRC) if wf is not None else None
        return None if i is None else float(-wf.mean(i))

    def criterion_on(self, cls, net: str):
        return next(
            (c for c in self.spec.acceptance if isinstance(c, cls) and getattr(c, "net", None) == net), None
        )

    def load_current(self, net: str, v: float) -> float:
        return sum(
            ld.current if ld.current is not None else v / ld.resistance
            for ld in self.spec.loads
            if ld.net == net
        )


Diagnoser = Callable[[Circuit], list[Diagnosis]]
DIAGNOSERS: list[Diagnoser] = []


def diagnoser(fn: Diagnoser) -> Diagnoser:
    DIAGNOSERS.append(fn)
    return fn


def diagnose(nl: Netlist, db: PartsDB, spec: Spec, report: VerificationReport, sim=None) -> list[Diagnosis]:
    c = Circuit(nl, db, spec, report, sim)
    out: list[Diagnosis] = []
    for fn in DIAGNOSERS:
        try:
            out += fn(c)
        except Exception as e:  # a diagnoser must never break verification
            out.append(Diagnosis("diagnosis.internal", f"{fn.__name__} failed: {e}", "ignore this entry"))
    return out


def _ms(x: float) -> str:
    return fmt_si(x, "s")


# --------------------------------------------------------------------- MC34063
@diagnoser
def mc34063(c: Circuit) -> list[Diagnosis]:
    out = []
    for u in c.refs(key="MC34063"):
        d = c.pd(u).design
        vcc, ipk, ct_net, fb = (c.net(u, p) for p in ("VCC", "IPK", "CT", "FB"))
        swe, swc = c.net(u, "SWE"), c.net(u, "SWC")
        ct = c.total_c(ct_net, c.gnd) if ct_net else 0
        if ct <= 0:
            out.append(
                Diagnosis(
                    "mc34063.timing",
                    f"{u}: no timing capacitor from CT to {c.gnd}: the oscillator does not run",
                    "Add a ceramic capacitor (e.g. 470p-1n) from CT to GND.",
                    [u],
                )
            )
            continue
        toff = ct * d.get("ct_swing", 0.5) / d.get("i_dischg", 140e-6)
        # ---- feedback set-point
        rbot = c.resistor(fb, c.gnd) if fb else None
        tops = [x for x in (c.resistors_from(fb, {c.gnd}) if fb else [])]
        vout_net = None
        if rbot and len(tops) == 1:
            rtop_ref, vout_net, rtop = tops[0]
            vset = d.get("vref", 1.25) * (1 + rtop / rbot[1])
            crit = c.criterion_on(DcVoltage, vout_net)
            if crit is not None:
                vt = (crit.min + crit.max) / 2
                want = rbot[1] * (vt / d.get("vref", 1.25) - 1)
                margin = min(crit.max - vset, vset - crit.min) / vt
                if not crit.min <= vset <= crit.max:
                    out.append(
                        Diagnosis(
                            "mc34063.setpoint",
                            f"{u}: feedback divider sets Vout = 1.25 x (1 + {fmt_value(rtop)}/{fmt_value(rbot[1])}) = {vset:.3g} V, outside {crit.min:g}..{crit.max:g} V",
                            f"Change {rtop_ref} to {fmt_value(nearest(want))} (Vout = {vt:g} V).",
                            [rtop_ref, rbot[0]],
                        )
                    )
                elif margin < 0.04 and c.failed(crit.key()):
                    out.append(
                        Diagnosis(
                            "mc34063.setpoint_margin",
                            f"{u}: set-point {vset:.3g} V leaves only {margin:.1%} to the window edge; the 1.25 V reference (+/-2 %) and resistor tolerances use that up",
                            f"Centre the set-point: {rtop_ref} = {fmt_value(nearest(want))}.",
                            [rtop_ref],
                        )
                    )
        elif fb:
            out.append(
                Diagnosis(
                    "mc34063.feedback",
                    f"{u}: FB is not a simple resistor divider from the output to {c.gnd}",
                    "Connect Rtop from the output to FB and Rbot from FB to GND (Vout = 1.25 V x (1 + Rtop/Rbot)).",
                    [u],
                )
            )
        # ---- current limit
        rsc = c.resistor(vcc, ipk) if vcc and ipk and vcc != ipk else None
        if rsc is None:
            out.append(
                Diagnosis(
                    "mc34063.current_sense",
                    f"{u}: no sense resistor between VCC and IPK: the cycle-by-cycle current limit cannot work",
                    "Insert Rsc (e.g. 0.1-0.33 ohm, 1 W) between the supply and IPK and feed the inductor from IPK.",
                    [u],
                )
            )
        elif vout_net is not None:
            ilim = d.get("v_ipk", 0.3) / rsc[1]
            vout = vset
            iout = c.load_current(vout_net, vout)
            vin = c.spec.power_input.v_min - c.spec.power_input.source_resistance * vout * iout / (
                0.8 * c.spec.power_input.v_min
            )
            ratio = (vout + 0.45 - vin) / max(vin - 0.3, 0.1)
            need = 2 * iout * (ratio + 1)
            crit = c.criterion_on(DcVoltage, vout_net)
            if iout > 0 and ilim < 0.9 * need and (crit is None or c.failed(crit.key())):
                out.append(
                    Diagnosis(
                        "mc34063.current_limit",
                        f"{u}: current limit {d.get('v_ipk', 0.3):g} V / {fmt_value(rsc[1])} ohm = {ilim:.2f} A, but the load needs a peak of ~2 x Iout x (ratio + 1) = {need:.2f} A at v_min (ratio {ratio:.2f}): the output sags at low input",
                        f"Reduce {rsc[0]} to {fmt_value(floor_to(d.get('v_ipk', 0.3) / need, E12))} ohm (check the inductor/diode/switch peak ratings for the new limit).",
                        [rsc[0]],
                    )
                )
            for lref in c.refs("inductor"):
                if ipk in c.nets(lref):
                    pk = [r.max for r in c.pd(lref).ratings if r.type == "current" and r.mode == "peak"]
                    if pk and ilim > pk[0] * c.spec.derating.current and c.rating_failures(lref):
                        out.append(
                            Diagnosis(
                                "mc34063.inductor_peak",
                                f"{lref}: the current limit ({ilim:.2f} A) is above the inductor's derated peak rating ({pk[0] * c.spec.derating.current:.2f} A)",
                                f"Raise {rsc[0]} or use an inductor rated above {ilim / c.spec.derating.current:.2f} A.",
                                [lref, rsc[0]],
                            )
                        )
        # ---- switch
        mos = [
            q
            for q in c.refs("mosfet")
            if swe and (c.net(q, "G") == swe or (c.resistor(swe, c.net(q, "G") or "") is not None))
        ]
        for q in mos:
            gate = c.net(q, "G")
            ciss = c.pd(q).design.get("ciss")
            pulls = [r for r, other, _ in c.resistors_from(gate) if other == c.gnd] if gate else []
            if gate != swe:
                pulls += [r for r, other, _ in c.resistors_from(swe) if other == c.gnd]
            if not pulls:
                out.append(
                    Diagnosis(
                        "mc34063.gate_pulldown",
                        f"{q}: the gate has no pull-down. SWE is an emitter follower that can only source current, so the MOSFET is never switched off (inductor current runs away, the transient aborts or the parts overheat)",
                        f"Add a resistor from {gate} to GND of about toff / (5 x Ciss) = {fmt_value(floor_to(toff / (5 * (ciss or 2e-9)), E12))} ohm.",
                        [q],
                    )
                )
            elif ciss:
                rpd = min(c.value(r) or 1e9 for r in pulls)
                tau = rpd * ciss
                if 3 * tau > toff:
                    out.append(
                        Diagnosis(
                            "mc34063.gate_turnoff",
                            f"{q}: turn-off time constant Rpd x Ciss = {fmt_value(rpd)} x {fmt_si(ciss, 'F')} = {_ms(tau)} is too slow for toff = {_ms(toff)} (needs 3 tau < toff)",
                            f"Reduce the pull-down to <= {fmt_value(floor_to(toff / (5 * ciss), E12))} ohm (or enlarge CT).",
                            pulls,
                        )
                    )
            if swc and vcc and swc != vcc:
                out.append(
                    Diagnosis(
                        "mc34063.drive",
                        f"{u}: with an external MOSFET, SWC (and DRC) must be tied to the supply so SWE can drive the gate high",
                        f"Connect SWC and DRC to {vcc}.",
                        [u],
                    )
                )
        if not mos and swc and swe == c.gnd:
            rsc_v = c.resistor(vcc, ipk) if vcc and ipk and vcc != ipk else None
            sw = [r.max for r in c.pd(u).ratings if r.type == "current" and r.pin == 1]
            if rsc_v and sw and d.get("v_ipk", 0.3) / rsc_v[1] > sw[0] * c.spec.derating.current:
                out.append(
                    Diagnosis(
                        "mc34063.internal_switch",
                        f"{u}: the current limit {d.get('v_ipk', 0.3) / rsc_v[1]:.2f} A exceeds the internal switch rating ({sw[0]:g} A, derated {sw[0] * c.spec.derating.current:.2f} A)",
                        "Drive an external logic-level MOSFET from SWE (gate resistor + pull-down) or raise Rsc.",
                        [u],
                    )
                )
    return out


# ---------------------------------------------------------------------- ripple
@diagnoser
def esr_ripple(c: Circuit) -> list[Diagnosis]:
    out = []
    for crit in c.spec.acceptance:
        if not isinstance(crit, Ripple) or not c.failed(crit.key()):
            continue
        caps = [r for r in c.refs("electrolytic", "capacitor") if c.nets(r) == {crit.net, c.gnd}]
        esrs = [(r, c.pd(r).design["esr"]) for r in caps if "esr" in c.pd(r).design]
        ipk = None
        for u in c.refs(key="MC34063"):
            rsc = c.resistor(c.net(u, "VCC"), c.net(u, "IPK"))
            if rsc:
                ipk = c.pd(u).design.get("v_ipk", 0.3) / rsc[1]
        if not esrs or ipk is None:
            continue
        esr_par = 1 / sum(1 / e for _, e in esrs)
        v_esr = ipk * esr_par
        if v_esr > 0.4 * crit.max:
            n = math.ceil(ipk * esrs[0][1] / (0.5 * crit.max))
            out.append(
                Diagnosis(
                    "ripple.esr",
                    f"{crit.net}: ripple is dominated by capacitor ESR — peak switch current {ipk:.2f} A x ESR {esr_par:.3g} ohm ({len(esrs)} capacitor(s) in parallel) = {v_esr * 1e3:.0f} mVpp vs {crit.max * 1e3:.0f} mVpp allowed; more capacitance of the same type barely helps",
                    f"Use {n} low-ESR capacitors in parallel (ESR / n), or lower the current limit.",
                    [r for r, _ in esrs],
                )
            )
    return out


# ------------------------------------------------------------------ regulators
@diagnoser
def linear_regulator(c: Circuit) -> list[Diagnosis]:
    out = []
    for u in c.refs("regulator"):
        d = c.pd(u).design
        if "vout" not in d:
            continue
        vin_net, vout_net = c.net(u, "IN"), c.net(u, "OUT")
        for sc in c.waveforms():
            v = c.v_net(sc, vin_net)
            if v is None:
                continue
            headroom = float(np.min(v)) - d["vout"]
            if headroom < d.get("dropout", 1.0):
                drops = _supply_path(c, vin_net, c.i_in(sc) or 0)
                out.append(
                    Diagnosis(
                        "regulator.dropout",
                        f"[{sc}] {u}: input is {float(np.min(v)):.2f} V, only {headroom:.2f} V above Vout {d['vout']:g} V; the dropout is {d.get('dropout', 0):g} V"
                        + (f" (supply path drops: {drops})" if drops else ""),
                        "Reduce the series drop (Schottky instead of a silicon diode, lower-resistance PTC) or use a lower-dropout regulator.",
                        [u],
                    )
                )
                break
        pf = [f for f in c.rating_failures(u) if "power" in f.message]
        if pf and vout_net:
            iout = c.load_current(vout_net, d["vout"])
            vmax = c.spec.power_input.v_max
            p = (vmax - d["vout"]) * iout
            out.append(
                Diagnosis(
                    "regulator.power",
                    f"{u}: dissipation (Vin - Vout) x Iout = ({vmax:g} - {d['vout']:g}) x {iout:g} A = {p:.2f} W is above its derated power rating",
                    "Drop part of the voltage in a series resistor before the regulator (sized for v_min headroom), use a regulator/package with a higher rating, or use a switching converter.",
                    [u],
                )
            )
    return out


def _supply_path(c: Circuit, target: str, i_in: float) -> str:
    """Series elements from the supply input to `target` with their estimated drops."""
    net, seen, parts, used = c.spec.power_input.pos_net, set(), [], set()
    while net != target and net not in seen:
        seen.add(net)
        nxt = [
            r
            for r in c.refs("diode", "ptc", "fuse", "resistor")
            if r not in used and net in c.nets(r) and c.gnd not in c.nets(r) and len(c.nets(r)) == 2
        ]
        if len(nxt) != 1:
            break
        r = nxt[0]
        used.add(r)
        pd = c.pd(r)
        if pd.kind == "diode":
            parts.append(f"{r} Vf ~{pd.design.get('vf', 0.7):g} V")
        else:
            res = pd.design.get("r") if pd.kind in ("ptc", "fuse") else c.value(r)
            if res:
                parts.append(f"{r} {res:g} ohm x {i_in:.3g} A = {res * i_in:.2f} V")
        net = next(iter(c.nets(r) - {net}))
    return ", ".join(parts)


# ----------------------------------------------------------------------- NE555
@diagnoser
def ne555(c: Circuit) -> list[Diagnosis]:
    out = []
    for u in c.refs(key="NE555"):
        dis, thr, trig, vcc = (c.net(u, p) for p in ("DIS", "THR", "TRIG", "VCC"))
        if thr != trig:
            out.append(
                Diagnosis(
                    "ne555.trigger",
                    f"{u}: TRIG and THR are on different nets; astable operation needs both on the timing capacitor",
                    "Connect TRIG to THR.",
                    [u],
                )
            )
            continue
        ra, rb = c.resistor(vcc, dis), c.resistor(dis, thr)
        cap = c.total_c(thr, c.gnd)
        if not (ra and rb and cap):
            continue
        f = 1 / (math.log(2) * (ra[1] + 2 * rb[1]) * cap)
        crit = c.criterion_on(Frequency, c.net(u, "OUT"))
        if crit is None or not c.failed(crit.key()):
            continue
        ft = math.sqrt(crit.min * crit.max)
        if not crit.min <= f <= crit.max:
            rb_new = nearest((1 / (math.log(2) * ft * cap) - ra[1]) / 2, E24_E96)
            out.append(
                Diagnosis(
                    "ne555.frequency",
                    f"{u}: f = 1/(ln2 (Ra + 2 Rb) C) = 1/(0.693 x ({fmt_value(ra[1])} + 2 x {fmt_value(rb[1])}) x {fmt_si(cap, 'F')}) = {f:.3g} Hz, outside {crit.min:g}..{crit.max:g} Hz",
                    f"Change {rb[0]} to {fmt_value(rb_new)} (f = {ft:.3g} Hz) or rescale C.",
                    [rb[0]],
                )
            )
        else:
            ctol = max((c.pd(r).tolerance or 0) for r in c.between(thr, c.gnd, "capacitor", "electrolytic"))
            out.append(
                Diagnosis(
                    "ne555.tolerance",
                    f"{u}: nominal f = {f:.3g} Hz is inside the window, but the timing capacitor's +/-{ctol:.0%} tolerance (plus resistors) pushes it out",
                    "Use a film timing capacitor (+/-10 % or better) and centre f in the window; avoid electrolytics for timing.",
                    [u],
                )
            )
    return out


# ---------------------------------------------------------------------- op-amp
@diagnoser
def opamp_gain(c: Circuit) -> list[Diagnosis]:
    out = []
    for crit in c.spec.acceptance:
        if not isinstance(crit, Gain) or not c.failed(crit.key()):
            continue
        for u in c.refs("opamp"):
            pd = c.pd(u)
            for sec in ("A", "B", ""):
                o, n = c.net(u, f"OUT{sec}"), c.net(u, f"INN{sec}")
                if o != crit.output_net or n is None:
                    continue
                rf, rg = c.resistor(o, n), c.resistor(n, c.gnd)
                if not (rf and rg):
                    continue
                g = 1 + rf[1] / rg[1]
                gt = (crit.min + crit.max) / 2
                vcc_net = c.net(u, "VCC")
                stim = next((s for s in c.spec.stimuli if s.net == crit.input_net), None)
                if not crit.min <= g <= crit.max:
                    out.append(
                        Diagnosis(
                            "opamp.gain",
                            f"{u}{sec}: G = 1 + Rf/Rg = 1 + {fmt_value(rf[1])}/{fmt_value(rg[1])} = {g:.4g}, outside {crit.min:g}..{crit.max:g}",
                            f"Change {rf[0]} to {fmt_value(nearest((gt - 1) * rg[1]))} (G = {gt:g}).",
                            [rf[0], rg[0]],
                        )
                    )
                elif stim is not None:
                    v_hi = g * (stim.dc + stim.amplitude)
                    rail = [
                        float(np.min(v)) for sc in c.waveforms() if (v := c.v_net(sc, vcc_net)) is not None
                    ]
                    vmax = min(rail) - pd.design.get("voh_drop", 1.5) if rail else None
                    if vmax is not None and v_hi > vmax:
                        out.append(
                            Diagnosis(
                                "opamp.swing",
                                f"{u}{sec}: output would need {v_hi:.2f} V but the op-amp only reaches ~{vmax:.2f} V (supply minus {pd.design.get('voh_drop', 1.5):g} V): the output clips",
                                "Lower the gain or raise the op-amp supply (less series drop, higher rail).",
                                [u],
                            )
                        )
    return out


# ------------------------------------------------------------------------- LED
@diagnoser
def led_current(c: Circuit) -> list[Diagnosis]:
    out = []
    for d in c.refs("led"):
        if not c.rating_failures(d):
            continue
        pd = c.pd(d)
        a = c.net(d, "A")
        rs = c.resistors_from(a) if a else []
        if len(rs) != 1:
            out.append(
                Diagnosis(
                    "led.resistor",
                    f"{d}: no single series resistor on the anode",
                    "Add a series resistor R = (Vdrive - Vf) / I.",
                    [d],
                )
            )
            continue
        r, src, rv = rs[0]
        vmax = max(
            (float(np.max(v)) for sc in c.waveforms() if (v := c.v_net(sc, src)) is not None), default=None
        )
        imax = min((x.max for x in pd.ratings if x.type == "current"), default=0.02)
        vf = pd.design.get("vf", 2.0)
        if vmax is None:
            continue
        i_now = (vmax - vf) / rv
        target = 0.5 * imax
        out.append(
            Diagnosis(
                "led.current",
                f"{d}: ~({vmax:.2f} V - Vf {vf:g} V) / {fmt_value(rv)} = {i_now * 1e3:.1f} mA exceeds its derated rating",
                f"Increase {r} to {fmt_value(ceil_to((vmax - vf) / target, E12))} (~{target * 1e3:.0f} mA).",
                [r, d],
            )
        )
    return out


# --------------------------------------------------------------- sim / supply
@diagnoser
def transient_abort(c: Circuit) -> list[Diagnosis]:
    aborted = [
        f
        for f in c.findings(r"^(sim|fault|tolerance)\.(op|sim)$")
        if "transient analysis aborted" in f.message
    ]
    if not aborted:
        return []
    hints = []
    for lref in c.refs("inductor"):
        ns = c.nets(lref)
        free = any(
            c.pd(r).kind in ("diode", "mosfet") for n in ns for r, _ in c.nl.nodes(n) if r != lref and c.pd(r)
        )
        if not free:
            hints.append(f"{lref} has no freewheel path (diode or switch) at either end")
    for q in c.refs("mosfet"):
        g = c.net(q, "G")
        if g and not any(o == c.gnd for _, o, _ in c.resistors_from(g)) and len(c.nl.nodes(g)) < 3:
            hints.append(f"{q} gate has no defined turn-off path")
    return [
        Diagnosis(
            "sim.transient_abort",
            "the transient simulation aborted ('timestep too small'): a node changes faster than ngspice can follow — usually a hard-switched node without a defined path (floating gate, inductor without freewheel diode) or an unrealistic part combination"
            + (": " + "; ".join(hints) if hints else ""),
            "Fix the listed structural problems; otherwise add a gate resistor (10 ohm) / pull-down, and make sure every inductor terminal has a diode or switch path.",
            [],
        )
    ]


@diagnoser
def supply_drop(c: Circuit) -> list[Diagnosis]:
    """Failures only at the lowest supply corner often come from series drops in the input path."""
    vmin = c.spec.power_input.v_min
    tag = f"vmin={vmin:g}V"
    rows = [r for r in c.failed_rows() if r.get("scenario") == tag]
    others = [r for r in c.failed_rows() if r.get("scenario", "").startswith(("vnom", "vmax"))]
    reg = [f for f in c.findings(r"^regression$") if tag in f.message]
    if not (rows or reg) or others:
        return []
    drops = _supply_path(c, "", c.i_in(tag) or 0)
    if not drops:
        return []
    return [
        Diagnosis(
            "supply.series_drop",
            f"failures appear only at the lowest supply ({vmin:g} V); the input path drops voltage before the circuit: {drops}",
            "Use a Schottky diode instead of a silicon rectifier (or a P-MOSFET reverse-polarity switch), a lower-resistance PTC, or more headroom in the design.",
            [],
        )
    ]
