"""LEDs need a series current-limiting resistor (the current itself is checked in simulation)."""

from __future__ import annotations

from . import Finding, RuleContext, Severity, rule


@rule("erc.led_current_limit", "Every LED has a dedicated series resistor")
def led_limit(ctx: RuleContext) -> list[Finding]:
    out = []
    for led in ctx.components_of_kind("led"):
        ok = False
        for pin in ("1", "2"):
            net = ctx.netlist.net_of(led.ref, pin)
            if net is None:
                continue
            nodes = ctx.netlist.nodes(net)
            others = [(r, p) for r, p in nodes if r != led.ref]
            kinds = [
                ctx.pdef(ctx.netlist.components[r]).kind if ctx.pdef(ctx.netlist.components[r]) else None
                for r, _ in others
            ]
            if others and "resistor" in kinds and all(k in ("resistor", "led") for k in kinds):
                ok = True
        if not ok:
            out.append(
                Finding(
                    "erc.led_current_limit",
                    Severity.ERROR,
                    f"{led.ref} has no series current-limiting resistor",
                    refs=[led.ref],
                    hint="Put a resistor alone in series with the LED (anode or cathode side).",
                )
            )
    return out
