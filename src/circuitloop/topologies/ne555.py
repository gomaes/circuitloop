"""NE555 astable oscillator, optionally driving an LED."""

from __future__ import annotations

import math

from ..spec import Frequency, InputPower, Spec
from . import Param, Topology
from .common import (
    Ctx,
    check_current,
    check_power,
    pick_capacitor,
    pick_resistor,
    place_cap,
    supply_front_end,
)
from .eseries import E6, E12, E24_E96, ceil_to, fmt_value, nearest
from .writer import DesignWriter, TopologyError

LN2 = math.log(2)


class NE555Astable(Topology):
    name = "ne555_astable"
    summary = "NE555 astable oscillator (square wave on the frequency net), optional LED indicator"
    description = (
        "f = 1.44 / ((Ra + 2 Rb) C). The timing capacitor is the smallest E6 value that keeps "
        "Ra + 2 Rb <= rmax, taken from the most precise capacitor family that has it; Ra is ~7 % of the "
        "total so the duty cycle is close to 50 %. The LED resistor is (Vcc - Voh_drop - Vf) / I_led, "
        "checked against the LED's derated current/power at v_max and against the input power limit."
    )
    params = {
        "c": Param("auto", "timing capacitor [F]"),
        "rmax": Param("1.5e6", "upper bound for Ra + 2 Rb [ohm]"),
        "led": Param("auto", "drive an LED from OUT: true/false (auto: if the description mentions an LED)"),
        "led_part": Param("auto", "parts-DB key of the LED (auto: red unless the description says green)"),
        "i_led": Param("0.01", "LED current [A]"),
    }

    def applicable(self, spec: Spec) -> str | None:
        if any(isinstance(c, Frequency) for c in spec.acceptance):
            return None
        return "needs a frequency criterion"

    def build(self, w: DesignWriter, cx: Ctx) -> str:
        sp = cx.spec
        pin = sp.power_input
        gnd = sp.ground_net
        fc = cx.criterion(Frequency)
        ft = math.sqrt(fc.min * fc.max)
        u_pd = cx.part("NE555")
        desc = sp.description.lower()
        led = cx.param("led", "led" in desc, lambda s: s.lower() in ("1", "true", "yes", "on"))
        i_led = cx.param("i_led", 0.01, float) if led else 0.0
        iq = u_pd.design.get("iq", 0.003)
        rail = "VCC" if cx.wants("reverse_polarity") or cx.wants("overcurrent") else pin.pos_net
        fe = supply_front_end(
            w, cx, iq + i_led + 0.002, rail, False, bulk=47e-6 if rail != pin.pos_net else None
        )
        v_lo, v_hi = pin.v_min - fe.drop(iq + i_led), pin.v_max
        if v_lo < u_pd.design.get("vcc_min", 4.5):
            raise TopologyError(f"supply {v_lo:.2f} V (after protection) is below the NE555 minimum")
        u = w.add("NE555", comment="astable timer")
        # ---- timing
        rmax = cx.param("rmax", 1.5e6, float)
        c = cx.param("c", ceil_to(1.0 / (LN2 * ft * rmax) * 0.999, E6), float)
        cpd = pick_capacitor(
            cx, c, v_hi, cx.v_abs, kinds=("capacitor",), what="timing capacitor", prefer="precise"
        )
        rtot = 1.0 / (LN2 * ft * c)
        ra = max(nearest(0.07 * rtot, E12), 1e3)
        rb = nearest((rtot - ra) / 2, E24_E96)
        f_est = 1.0 / (LN2 * (ra + 2 * rb) * c)
        duty = (ra + rb) / (ra + 2 * rb)
        r1 = w.add(pick_resistor(cx, ra, v_hi**2 / ra).key, fmt_value(ra), "Ra (VCC-DIS)")
        r2 = w.add(pick_resistor(cx, rb, v_hi**2 / rb).key, fmt_value(rb), "Rb (DIS-THR)")
        ct = w.add(cpd.key, fmt_value(c), f"timing capacitor (+/-{(cpd.tolerance or 0):.0%})")
        tol = (cpd.tolerance or 0) + 2 * 0.01
        cx.note(f"target f = {ft:.4g} Hz (window {fc.min:g}..{fc.max:g} Hz)")
        cx.note(
            f"f = 1/(ln2 (Ra + 2 Rb) C) = 1/(0.693 x ({fmt_value(ra)} + 2 x {fmt_value(rb)}) x {fmt_value(c)}) "
            f"= {f_est:.4g} Hz, duty {duty:.0%}"
        )
        window = min(fc.max / f_est - 1, 1 - fc.min / f_est)
        cx.note(f"tolerance stack ~+/-{tol:.0%} ({cpd.key} + resistors) vs window +/-{window:.0%}")
        if window < tol:
            cx.note(
                "WARNING: the frequency window is narrower than the tolerance stack; use a tighter capacitor"
            )
        out = fc.net
        w.connect(rail, f"{u}.VCC", f"{u}.RESET", f"{r1}.1")
        w.connect(gnd, f"{u}.GND", f"{ct}.2")
        w.connect("DIS", f"{r1}.2", f"{r2}.1", f"{u}.DIS")
        w.connect("THR", f"{r2}.2", f"{ct}.1", f"{u}.THR", f"{u}.TRIG")
        w.connect(out, f"{u}.OUT")
        place_cap(w, cx, 10e-9, "CTRL", gnd, v_hi, "CTRL noise filter")
        w.connect("CTRL", f"{u}.CTRL")
        place_cap(
            w, cx, ceil_to(max(u_pd.decoupling[0].min, 100e-9), E6), rail, gnd, v_hi, f"{u} VCC decoupling"
        )
        if led:
            self._led(w, cx, out, v_lo, v_hi, i_led, u_pd.design.get("voh_drop", 1.7), iq, ra + rb)
        return f"NE555 astable, f ~ {f_est:.3g} Hz" + (", LED on OUT" if led else "") + "."

    def _led(
        self,
        w: DesignWriter,
        cx: Ctx,
        out: str,
        v_lo: float,
        v_hi: float,
        i_led: float,
        voh: float,
        iq: float,
        rdis: float,
    ) -> None:
        sp = cx.spec
        desc = sp.description.lower()
        default = "LED_GREEN_5MM" if "green" in desc else "LED_RED_5MM"
        lpd = cx.part(cx.param("led_part", default))
        vf = lpd.design.get("vf", 2.0)
        v_nom = sp.power_input.v_nom - (sp.power_input.v_min - v_lo)
        r = ceil_to((v_nom - voh - vf) / i_led, E12)
        i_hi = (v_hi - voh - vf) / r
        why = check_current(lpd, cx, peak=i_hi) or check_power(lpd, cx, vf * i_hi)
        if why:
            r = ceil_to((v_hi - voh - vf) / (0.95 * min(i_led, i_hi * 0.8)), E12)
            i_hi = (v_hi - voh - vf) / r
        rp = pick_resistor(cx, r, (v_hi - voh - vf) * i_hi, what="LED resistor")
        rl = w.add(rp.key, fmt_value(r), "LED current limit")
        d = w.add(lpd.key, comment="indicator LED")
        w.connect(out, f"{rl}.1")
        w.connect("LED_A", f"{rl}.2", f"{d}.A")
        w.connect(sp.ground_net, f"{d}.K")
        cx.note(
            f"LED: R = (Vcc - Voh_drop - Vf) / I = ({v_nom:.2f} - {voh:g} - {vf:g}) / {i_led * 1e3:g} mA -> {fmt_value(r)} "
            f"(I = {i_hi * 1e3:.1f} mA at v_max)"
        )
        ip = cx.criterion(InputPower)
        if ip is not None:
            p = v_hi * (iq + 0.5 * i_hi + 0.5 * v_hi / rdis)
            cx.note(f"input power estimate at v_max: {p:.3g} W (limit {ip.max:g} W)")
            if p > ip.max:
                raise TopologyError(
                    f"input power ~{p:.3g} W exceeds {ip.max:g} W: lower i_led (--set i_led=...)"
                )
