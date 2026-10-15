"""Structural presence of protection required by spec.protection (Phase 3+).

reverse_polarity / overvoltage are verified numerically by fault injection (G3).
"""

from __future__ import annotations

from . import PHASE_HARDEN, Finding, RuleContext, Severity, rule


def _nets(ctx: RuleContext, ref: str) -> set[str]:
    return {n for (r, _), n in ctx.netlist.pin_net.items() if r == ref}


@rule("protect.structure", "Protection components required by spec.protection are present", PHASE_HARDEN)
def protection(ctx: RuleContext) -> list[Finding]:
    out = []
    spec = ctx.spec
    pos, gnd = spec.power_input.pos_net, spec.ground_net
    req = set(spec.protection)
    if "overcurrent" in req:
        fuses = [
            c
            for c in ctx.components_of_kind("ptc", "fuse")
            if pos in _nets(ctx, c.ref) and len(_nets(ctx, c.ref)) == 2
        ]
        if not fuses:
            out.append(
                Finding(
                    "protect.overcurrent",
                    Severity.ERROR,
                    f"no fuse/PTC in series with the input net '{pos}'",
                    nets=[pos],
                    hint=f"Insert a PTC between '{pos}' and the rest of the circuit.",
                )
            )
    if "esd" in req:
        ext = {pos} | {s.net for s in spec.stimuli}
        for net in sorted(ext):
            clamps = [c for c in ctx.components_of_kind("tvs", "zener") if _nets(ctx, c.ref) == {net, gnd}]
            if not clamps:
                out.append(
                    Finding(
                        "protect.esd",
                        Severity.ERROR,
                        f"no TVS/Zener clamp from external net '{net}' to '{gnd}'",
                        nets=[net],
                    )
                )
    if "input_protection" in req:
        for s in spec.stimuli:
            if not any(
                r in ctx.netlist.components
                and ctx.pdef(ctx.netlist.components[r])
                and ctx.pdef(ctx.netlist.components[r]).kind == "resistor"
                for r, _ in ctx.netlist.nodes(s.net)
            ):
                out.append(
                    Finding(
                        "protect.input_protection",
                        Severity.ERROR,
                        f"signal input '{s.net}' has no series resistor",
                        nets=[s.net],
                    )
                )
    return out
