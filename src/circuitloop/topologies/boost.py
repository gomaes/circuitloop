"""MC34063 step-up (boost) converter with an external logic-level MOSFET.

The internal Darlington switch is not offered: its behavioural model has no collector clamp, so the
discontinuous-mode ringing of the switch node is not simulated realistically.
"""

from __future__ import annotations

import math

from ..partsdb import PartDef
from ..spec import InputCurrent, Ripple, Spec
from ..units import fmt_si
from . import Param, Topology
from .common import (
    Ctx,
    check_current,
    check_power,
    check_voltage,
    choose,
    connector,
    pick_resistor,
    place_cap,
    rating_max,
    supply_front_end,
    value_fits,
)
from .eseries import E6, E12, E24, E24_E96, candidates, ceil_to, floor_to, fmt_value, nearest
from .writer import DesignWriter, TopologyError


class MC34063Boost(Topology):
    name = "mc34063_boost"
    summary = "MC34063 boost converter (external logic-level MOSFET) for a DC rail above the input"
    description = (
        "ON Semiconductor AN920 method: ratio = (Vout + Vf - Vin_min) / (Vin_min - Vsat), "
        "ton from the switching frequency, Ipk = 2 Iout (ratio + 1), Rsc = 0.3 V / Ipk, "
        "Lmin = (Vin_min - Vsat) ton / Ipk (L = 2 x Lmin, E6), Co >= 9 Iout ton / Vripple and enough "
        "parallel low-ESR capacitors that Ipk x ESR <= Vripple / 2, Vout = 1.25 V (1 + Rtop/Rbot). "
        "SWE drives the MOSFET gate as an emitter follower; the gate pull-down discharges Ciss within "
        "toff / 5."
    )
    params = {
        "f": Param("50e3", "switching frequency used for the AN920 sizing [Hz]"),
        "eff": Param("0.8", "assumed efficiency for the input-current estimate"),
        "mosfet": Param("IRLZ44N", "parts-DB key of the external MOSFET"),
    }

    def applicable(self, spec: Spec) -> str | None:
        from ..spec import DcVoltage

        pin = spec.power_input
        for c in spec.acceptance:
            if isinstance(c, DcVoltage) and c.net != pin.pos_net and c.min > pin.v_max:
                return None
        return "needs a dc_voltage criterion on a net above the maximum input voltage"

    def build(self, w: DesignWriter, cx: Ctx) -> str:
        sp = cx.spec
        pin = sp.power_input
        gnd = sp.ground_net
        crit = cx.dc_target(lambda c: c.min > pin.v_max)
        vout = (crit.min + crit.max) / 2
        iout = cx.load_current(crit.net, vout)
        if iout <= 0:
            raise TopologyError(f"no load on {crit.net} in spec.loads")
        rc = next((c for c in sp.acceptance if isinstance(c, Ripple) and c.net == crit.net), None)
        vripple = rc.max if rc else 0.01 * vout
        ctl = cx.part("MC34063")
        d = ctl.design
        f = cx.param("f", 50e3, float)
        eff = cx.param("eff", 0.8, float)
        i_in = vout * iout / (eff * pin.v_min)
        ic = cx.criterion(InputCurrent)
        if ic is not None and i_in > ic.max:
            raise TopologyError(
                f"estimated input current {i_in:.2f} A (Pout / (eff x Vin_min)) exceeds the {ic.max:g} A limit"
            )
        cx.note(
            f"target {crit.net} = {vout:g} V, Iout = {fmt_si(iout, 'A')}; Iin ~ Vout Iout / (eff Vin_min) = {i_in:.3g} A"
        )
        # ---- front end (connector, PTC, reverse diode) and input capacitors
        protected = cx.wants("overcurrent") or cx.wants("reverse_polarity")
        rail = "VIN" if protected and pin.pos_net != "VIN" else ("VIN_P" if protected else pin.pos_net)
        bulk = ceil_to(max(100e-6 * i_in, 100e-6), E6)
        fe = supply_front_end(w, cx, i_in, rail, True, bulk=bulk)
        vin_min = pin.v_min - fe.drop(i_in) - 0.1 * i_in  # + sense-resistor drop (~0.1 ohm)
        cx.note(f"Vin_min at the converter = {pin.v_min:g} V - source/protection drops = {vin_min:.3g} V")
        # ---- switch, timing, peak current
        vf = 0.45
        vsat = 0.1  # MOSFET Rds(on) x Ipk
        ratio = (vout + vf - vin_min) / (vin_min - vsat)
        ipk = 2 * iout * (ratio + 1)
        max_ratio = d["i_dischg"] / d["i_chg"]
        if ratio > 0.8 * max_ratio:
            raise TopologyError(
                f"ton/toff = {ratio:.2f} exceeds what the MC34063 oscillator allows (~{max_ratio:.1f})"
            )
        t = 1.0 / f
        toff_d = t / (ratio + 1)
        ton_d = t - toff_d
        ct = nearest(ton_d * d["i_chg"] / d["ct_swing"], E12)
        ton = ct * d["ct_swing"] / d["i_chg"]
        toff = ct * d["ct_swing"] / d["i_dischg"]
        cx.note(
            f"ton/toff = (Vout + Vf - Vin_min) / (Vin_min - Vsat) = {ratio:.3g}; at f = {f:g} Hz: ton = {ton_d * 1e6:.3g} us"
        )
        cx.note(
            f"CT = ton x I_chg / {d['ct_swing']:g} V -> {fmt_value(ct)} (oscillator: ton {ton * 1e6:.3g} us, toff {toff * 1e6:.3g} us)"
        )
        rsc = floor_to(d["v_ipk"] / ipk, E12)
        ilim = d["v_ipk"] / rsc
        cx.note(
            f"Ipk = 2 Iout (ratio + 1) = {ipk:.3g} A; Rsc = {d['v_ipk']:g} V / Ipk -> {fmt_value(rsc)} ohm (limit {ilim:.3g} A)"
        )
        # ---- inductor
        lmin = (vin_min - vsat) * ton / ipk
        lval = ceil_to(2 * lmin, E6)
        ind = choose(
            [p for p in cx.of_kind("inductor") if value_fits(p, lval)],
            lambda p: check_current(p.for_value(lval), cx, peak=ilim * 1.05, rms=i_in * 1.1),
            f"inductor ({fmt_value(lval)}, {ilim:.2f} A peak)",
            key=lambda p: rating_max(p, "current") or 0,
        )
        cx.note(
            f"Lmin = (Vin_min - Vsat) ton / Ipk = {lmin * 1e6:.3g} uH -> L = 2 x Lmin -> {fmt_value(lval)}H"
        )
        # ---- output diode
        dio = choose(
            [p for p in cx.of_kind("diode") if "vf" in p.design],
            lambda p: (
                check_current(p, cx, peak=ilim, avg=iout, rms=iout * 1.5)
                or check_power(p, cx, 1.2 * p.design["vf"] * iout)
                or _rev(p, cx, crit.max)
            ),
            "output rectifier",
            key=lambda p: (p.design.get("vf", 9), rating_max(p, "current") or 0),
        )
        # ---- output capacitors
        co_min = 9 * iout * ton / vripple

        def n_ok(n: int) -> bool:
            return n <= 6

        def size_bank(p):
            """(n, value, ESR) of a parallel bank of part p meeting Co and Ipk x ESR / n <= Vripple / 2."""
            n = 1
            for _ in range(8):
                c = ceil_to(max(2 * co_min / n, 100e-6), E6)
                c = min(max(c, p.value_min or c), p.value_max or c)
                esr = p.for_value(c).design.get("esr")
                if esr is None:
                    return None
                need = max(1, math.ceil(ilim * esr / (0.5 * vripple) - 1e-9))
                if need <= n:
                    return n, c, esr
                n = need
            return None

        banks = {}
        for p in cx.of_kind("electrolytic"):
            bank = size_bank(p)
            if bank is not None and n_ok(bank[0]):
                banks[p.key] = bank
        esr_ok = choose(
            [p for p in cx.of_kind("electrolytic") if p.key in banks],
            lambda p: (
                check_voltage(p.for_value(banks[p.key][1]), cx, crit.max * 1.05, None)
                or check_current(
                    p.for_value(banks[p.key][1]), cx, rms=iout * math.sqrt(max(ratio, 0.1)) / banks[p.key][0]
                )
            ),
            "output capacitor",
            key=lambda p: (banks[p.key][0], banks[p.key][2], rating_max(p, "voltage") or 0),
        )
        n_cap, c_each, esr = banks[esr_ok.key]
        i_ripple = iout * math.sqrt(max(ratio, 0.1)) / n_cap
        cx.note(
            f"Co >= 9 Iout ton / Vripple = {co_min * 1e6:.3g} uF; ESR: Ipk x ESR/n <= Vripple/2 -> n = {n_cap} x "
            f"{esr_ok.key} (ESR {esr:g} ohm) of {fmt_value(c_each)}F"
        )
        # ---- feedback divider
        best = None
        for rbot in candidates(E24, 1e3, 4.7e3):
            rtop = nearest(rbot * (vout / d["vref"] - 1), E24_E96)
            v = d["vref"] * (1 + rtop / rbot)
            key = (round(abs(v - vout) / vout, 4), abs(math.log(rbot / 1.5e3)))
            if best is None or key < best[0]:
                best = (key, rbot, rtop, v)
        _, rbot, rtop, vset = best
        cx.note(
            f"Vout = {d['vref']:g} V x (1 + Rtop/Rbot) = 1.25 x (1 + {fmt_value(rtop)}/{fmt_value(rbot)}) = {vset:.4g} V"
        )
        # ---- place parts
        u = w.add("MC34063", comment="boost controller")
        r_sc = w.add(
            pick_resistor(cx, rsc, (i_in * 1.15) ** 2 * rsc, what="current-sense resistor").key,
            fmt_value(rsc),
            f"current sense: limit {d['v_ipk']:g} V / Rsc = {ilim:.2f} A",
        )
        lr = w.add(ind.key, fmt_value(lval), "boost inductor")
        dr = w.add(dio.key, comment=f"output rectifier (Vf ~{dio.design['vf']:g} V)")
        place_cap(
            w, cx, ct, "CT", gnd, 5.0, "oscillator timing capacitor", kinds=("capacitor",), prefer="ceramic"
        )
        w.connect(fe.rail, f"{u}.VCC", f"{r_sc}.1")
        w.connect("IPK", f"{r_sc}.2", f"{u}.IPK", f"{lr}.1")
        w.connect("SW", f"{lr}.2", f"{dr}.A")
        w.connect("CT", f"{u}.CT")
        w.connect(gnd, f"{u}.GND")
        self._mosfet(w, cx, u, fe.rail, vin_min, toff, ilim, i_in, crit.max)
        place_cap(w, cx, 100e-9, fe.rail, gnd, pin.v_max, f"{u} VCC decoupling")
        for k in range(n_cap):
            place_cap(
                w, cx, c_each, crit.net, gnd, crit.max * 1.05,
                "output capacitor" + (f" {k + 1}/{n_cap} (parallel: ESR / n)" if n_cap > 1 else ""),
                kinds=("electrolytic",), prefer="low_esr", i_rms=i_ripple, keys=(esr_ok.key,),
            )  # fmt: skip
        place_cap(w, cx, 100e-9, crit.net, gnd, crit.max * 1.05, "output HF decoupling")
        w.connect(crit.net, f"{dr}.K")
        r4 = w.add(
            pick_resistor(cx, rtop, crit.max**2 / (rtop + rbot)).key, fmt_value(rtop), "feedback divider top"
        )
        r5 = w.add(pick_resistor(cx, rbot, 2.0 / rbot).key, fmt_value(rbot), "feedback divider bottom")
        w.connect(crit.net, f"{r4}.1")
        w.connect("FB", f"{r4}.2", f"{r5}.1", f"{u}.FB")
        w.connect(gnd, f"{r5}.2")
        j = connector(w, 2, f"output ({crit.net} / {gnd})", True)
        w.connect(crit.net, f"{j}.1")
        w.connect(gnd, f"{j}.2")
        return f"MC34063 boost {pin.v_min:g}-{pin.v_max:g} V -> {vout:g} V / {fmt_si(iout, 'A')} ."

    def _mosfet(
        self,
        w,
        cx: Ctx,
        u: str,
        rail: str,
        vin_min: float,
        toff: float,
        ilim: float,
        i_in: float,
        vmax: float,
    ) -> None:
        sp = cx.spec
        q = cx.part(cx.param("mosfet", "IRLZ44N"))
        ciss = q.design.get("ciss", 2e-9)
        vgs = vin_min - cx.part("MC34063").design.get("v_drive", 1.0)
        why = (
            check_current(q, cx, peak=ilim, rms=i_in * 1.2)
            or _vds(q, cx, vmax * 1.1)
            or (
                f"gate drive {vgs:.2f} V < {q.design['vgs_min']:g} V"
                if vgs < q.design.get("vgs_min", 4.0)
                else None
            )
        )
        if why:
            raise TopologyError(f"{q.key} cannot be the switch: {why}")
        rpd = floor_to(max(toff / (5 * ciss), 100.0), E12)
        p_rpd = (sp.power_input.v_max - 1.0) ** 2 / rpd
        qr = w.add(q.key, comment="external switch (logic-level MOSFET)")
        rg = w.add(pick_resistor(cx, 10.0, 0.05).key, "10", "gate resistor (damps ringing)")
        rp = w.add(
            pick_resistor(cx, rpd, p_rpd, what="gate pull-down").key,
            fmt_value(rpd),
            "gate pull-down: turn-off path",
        )
        w.connect(rail, f"{u}.SWC", f"{u}.DRC")
        w.connect("DRV", f"{u}.SWE", f"{rg}.1")
        w.connect("GATE", f"{rg}.2", f"{qr}.G", f"{rp}.1")
        w.connect("SW", f"{qr}.D")
        w.connect(sp.ground_net, f"{qr}.S", f"{rp}.2")
        cx.note(
            f"MOSFET {q.key}: SWE drives the gate (emitter follower, Vgs ~ {vgs:.2f} V at Vin_min); "
            f"pull-down <= toff / (5 Ciss) = {toff * 1e6:.3g} us / (5 x {ciss * 1e9:.3g} nF) -> {fmt_value(rpd)} ohm"
        )


def _vds(q: PartDef, cx: Ctx, v: float) -> str | None:
    d, s = q.pin_by_name("D"), q.pin_by_name("S")
    for r in q.ratings:
        if r.type == "voltage" and r.pins == [d, s] and r.max * cx.der_v < v:
            return f"Vds rating {r.max:g} V x {cx.der_v:g} < {v:.3g} V"
    return None


def _rev(pd: PartDef, cx: Ctx, vout_max: float) -> str | None:
    for r in pd.ratings:
        if r.type == "voltage" and r.max * cx.der_v < vout_max * 1.1:
            return f"reverse voltage {r.max:g} V x {cx.der_v:g} < {vout_max * 1.1:.3g} V"
    return None
