"""Single-supply non-inverting amplifier (LM358)."""

from __future__ import annotations

import math

from ..spec import Gain, Spec
from . import Param, Topology
from .common import Ctx, connector, pick_resistor, place_cap, supply_front_end
from .eseries import E6, E24, E24_E96, candidates, ceil_to, fmt_value, nearest
from .writer import DesignWriter, TopologyError


class NonInvertingAmp(Topology):
    name = "noninverting_amp"
    summary = "single-supply non-inverting op-amp amplifier, G = 1 + Rf/Rg (unused section terminated)"
    description = (
        "Rg is chosen from E24 (1k..10k) and Rf from E24/E96 so that 1 + Rf/Rg is closest to the target "
        "gain (ties: feedback network near rsum). The output swing G x (input range) is checked "
        "against the op-amp's output range at the lowest supply. With input_protection a series "
        "resistor is placed in the signal input."
    )
    params = {
        "opamp": Param("LM358", "parts-DB key of the dual op-amp"),
        "rsum": Param("20e3", "preferred Rf + Rg [ohm]"),
        "rin": Param("1e3", "input series resistor with input_protection [ohm]"),
    }

    def applicable(self, spec: Spec) -> str | None:
        if any(isinstance(c, Gain) and c.min >= 1 for c in spec.acceptance):
            return None
        return "needs a gain criterion >= 1"

    def build(self, w: DesignWriter, cx: Ctx) -> str:
        sp = cx.spec
        pin = sp.power_input
        gnd = sp.ground_net
        gc = next(c for c in sp.acceptance if isinstance(c, Gain))
        gt = (gc.min + gc.max) / 2
        opd = cx.part(cx.param("opamp", "LM358"))
        names = {p.name for p in opd.pins.values()}
        if not {"OUTA", "INNA", "INPA", "OUTB", "INNB", "INPB", "VCC", "GND"} <= names:
            raise TopologyError(f"{opd.key} is not a dual op-amp with LM358-style pin names")
        iq = opd.design.get("iq", 0.001)
        rail = "VCC" if cx.wants("reverse_polarity") or cx.wants("overcurrent") else pin.pos_net
        fe = supply_front_end(w, cx, iq + 0.005, rail, False, bulk=10e-6 if rail != pin.pos_net else None)
        v_lo, v_hi = pin.v_min - fe.drop(iq + 0.005), pin.v_max
        # ---- gain network
        rsum = cx.param("rsum", 20e3, float)
        best = None
        for rg in candidates(E24, 1e3, 10e3):
            rf = nearest((gt - 1) * rg, E24_E96)
            err = abs(1 + rf / rg - gt) / gt
            key = (round(err, 4), abs(math.log((rf + rg) / rsum)))
            if best is None or key < best[0]:
                best = (key, rg, rf)
        _, rg, rf = best
        g = 1 + rf / rg
        u = w.add(opd.key, comment="op-amp (section A amplifies, B unused)")
        r1 = w.add(pick_resistor(cx, rf, v_hi**2 / rf).key, fmt_value(rf), "Rf (OUT-FB)")
        r2 = w.add(pick_resistor(cx, rg, v_hi**2 / rg).key, fmt_value(rg), "Rg (FB-GND)")
        cx.note(
            f"target gain {gt:.4g} (window {gc.min:g}..{gc.max:g}); G = 1 + Rf/Rg = 1 + {fmt_value(rf)}/{fmt_value(rg)} = {g:.4g}"
        )
        # ---- signal range vs. output swing
        stim = next((s for s in sp.stimuli if s.net == gc.input_net), None)
        if stim is not None:
            lo, hi = stim.dc - stim.amplitude, stim.dc + stim.amplitude
            vo_hi = g * hi
            vo_max = v_lo - opd.design.get("voh_drop", 1.5)
            cx.note(
                f"output swing {g * lo:.3g}..{vo_hi:.3g} V; op-amp output range at v_min ~0..{vo_max:.3g} V"
            )
            if vo_hi > vo_max:
                raise TopologyError(
                    f"output would need {vo_hi:.2f} V but {opd.key} only reaches ~{vo_max:.2f} V at the lowest supply"
                )
            if lo < 0:
                cx.note("WARNING: input goes below ground; a single-supply amplifier clips it")
        inp = gc.input_net
        if cx.wants("input_protection"):
            rin = cx.param("rin", 1e3, float)
            r3 = w.add(pick_resistor(cx, rin, 0.01).key, fmt_value(rin), "input series protection")
            w.connect(inp, f"{r3}.1")
            inp = f"{gc.input_net}_R"
            w.connect(inp, f"{r3}.2")
            cx.note(f"{r3}: {fmt_value(rin)} series resistor limits the input clamp current")
        w.connect(inp, f"{u}.INPA")
        w.connect(gc.output_net, f"{u}.OUTA", f"{r1}.1")
        w.connect("FB", f"{r1}.2", f"{r2}.1", f"{u}.INNA")
        w.connect(rail, f"{u}.VCC")
        w.connect(gnd, f"{u}.GND", f"{r2}.2", f"{u}.INPB")
        w.connect("FB_B", f"{u}.OUTB", f"{u}.INNB", comment="unused section: grounded follower")
        dec = max((d.min for d in opd.decoupling), default=100e-9)
        place_cap(w, cx, ceil_to(max(dec, 100e-9), E6), rail, gnd, v_hi, f"{u} VCC decoupling")
        j = connector(w, 3, f"signal ({gc.input_net} / {gc.output_net} / {gnd})", False)
        w.connect(gc.input_net, f"{j}.1")
        w.connect(gc.output_net, f"{j}.2")
        w.connect(gnd, f"{j}.3")
        return f"Non-inverting amplifier, G = {g:.4g} ({opd.key})."
