"""Fixed-output linear regulator (78xx / LDO) with the capacitors its datasheet requires."""

from __future__ import annotations

from ..partsdb import PartDef
from ..spec import Spec
from . import Param, Topology
from .common import (
    Ctx,
    check_current,
    check_power,
    check_voltage,
    choose,
    connector,
    decoupling,
    supply_front_end,
)
from .writer import DesignWriter, TopologyError


class LinearRegulator(Topology):
    name = "ldo_regulator"
    summary = "fixed-output linear regulator (LDO or 78xx) for a DC rail below the input voltage"
    description = (
        "Picks the regulator from the parts DB whose output voltage and tolerance fit the dc_voltage "
        "window, whose dropout fits the lowest input (after protection drops) and whose dissipation "
        "(Vin_max - Vout) x I + Vin x Iq fits the derated power rating. Adds the input/output "
        "capacitors from the part's decoupling data."
    )
    params = {
        "regulator": Param("auto", "parts-DB key of the regulator to use"),
        "iout": Param("auto", "load current [A] (default: from spec.loads on the output net)"),
    }

    def applicable(self, spec: Spec) -> str | None:
        from ..spec import DcVoltage

        pin = spec.power_input
        for c in spec.acceptance:
            if isinstance(c, DcVoltage) and c.net != pin.pos_net and c.max < pin.v_min:
                return None
        return "needs a dc_voltage criterion on a net below the minimum input voltage"

    def build(self, w: DesignWriter, cx: Ctx) -> str:
        sp = cx.spec
        pin = sp.power_input
        crit = cx.dc_target(lambda c: c.max < pin.v_min)
        vt, half = (crit.min + crit.max) / 2, (crit.max - crit.min) / 2
        iout = cx.param("iout", cx.load_current(crit.net, vt), float)
        if iout <= 0:
            raise TopologyError(f"no load on {crit.net}: set spec.loads or --set iout=<A>")
        regs = [p for p in cx.of_kind("regulator") if "vout" in p.design]
        forced = cx.params.get("regulator")
        if forced and forced != "auto":
            regs = [cx.part(forced)]

        def tol(pd: PartDef) -> float:
            prm = pd.spice.params.get("vout") if pd.spice else None
            return prm.tolerance if prm else 0.05

        iq_max = max((p.design.get("iq", 0.005) for p in regs), default=0.005)
        # the protection front-end is sized for the worst-case input current
        i_in = iout + iq_max
        rail = "VREG_IN" if _protected(cx) else pin.pos_net
        fe = supply_front_end(w, cx, i_in, rail, True, bulk=10e-6)
        vin_lo = pin.v_min - fe.drop(i_in)
        vin_hi = pin.v_max

        def ok(pd: PartDef) -> str | None:
            vo, t, dr, iq = (
                pd.design["vout"],
                tol(pd),
                pd.design.get("dropout", 2.0),
                pd.design.get("iq", 0.005),
            )
            if abs(vo - vt) + vo * t > 0.8 * half:
                return f"output {vo:g} V +/-{t:.0%} does not fit {crit.min:g}..{crit.max:g} V with margin"
            if vin_lo - dr < vo * (1 + t) + 0.1:
                return f"dropout: input {vin_lo:.2f} V at v_min (after protection) < {vo * (1 + t) + dr + 0.1:.2f} V needed"
            p = (vin_hi - vo * (1 - t)) * iout + vin_hi * iq
            return (
                check_current(pd, cx, peak=iout)
                or check_power(pd, cx, p)
                or check_voltage(pd, cx, vin_hi, cx.v_abs)
            )

        reg = choose(
            regs,
            ok,
            f"regulator for {vt:g} V / {iout:g} A",
            key=lambda p: (tol(p), p.design.get("dropout", 9)),
        )
        u = w.add(reg.key, comment=f"{reg.design['vout']:g} V regulator")
        names = {p.name: n for n, p in reg.pins.items()}
        w.connect(fe.rail, f"{u}.IN")
        w.connect(crit.net, f"{u}.OUT")
        w.connect(sp.ground_net, f"{u}.GND")
        nets = {names["IN"]: fe.rail, names["OUT"]: crit.net, names["GND"]: sp.ground_net}
        decoupling(w, cx, u, nets, vin_hi)
        j = connector(w, 2, f"output ({crit.net} / {sp.ground_net})", True)
        w.connect(crit.net, f"{j}.1")
        w.connect(sp.ground_net, f"{j}.2")
        p = (vin_hi - reg.design["vout"]) * iout + vin_hi * reg.design.get("iq", 0.005)
        cx.note(f"target {crit.net} = {vt:g} V (window {crit.min:g}..{crit.max:g} V), load {iout:g} A")
        cx.note(
            f"{u} {reg.key}: Vout {reg.design['vout']:g} V +/-{tol(reg):.0%}, dropout {reg.design.get('dropout', 0):g} V; "
            f"input {vin_lo:.2f}..{vin_hi:g} V"
        )
        cx.note(
            f"{u} dissipation at v_max: ({vin_hi:g} - {reg.design['vout']:g}) x {iout:g} + Iq x Vin = {p:.3g} W"
        )
        return f"Linear regulator {pin.v_min:g}-{pin.v_max:g} V -> {vt:g} V / {iout:g} A ({reg.key})."


def _protected(cx: Ctx) -> bool:
    return cx.wants("overcurrent") or cx.wants("reverse_polarity")
