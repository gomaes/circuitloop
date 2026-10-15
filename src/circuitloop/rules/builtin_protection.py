"""Structural presence of protection required by spec.protection (Phase 3+).

reverse_polarity / overvoltage are verified numerically by fault injection (G3).
"""

from __future__ import annotations

from . import PHASE_HARDEN, Finding, RuleContext, Severity, rule


def _nets(ctx: RuleContext, ref: str) -> set[str]:
    return {n for (r, _), n in ctx.netlist.pin_net.items() if r == ref}


_SERIES = ("diode", "ptc", "fuse", "resistor")


def input_chain(ctx: RuleContext) -> list[str]:
    """Refs of the series elements between the supply input and the rest of the circuit.

    Starting at the input net, follow two-pin series parts as long as the net has exactly one
    such outgoing element (connectors and shunt parts to ground are ignored).
    """
    gnd = ctx.spec.ground_net
    net, seen, chain = ctx.spec.power_input.pos_net, set(), []
    while net not in seen:
        seen.add(net)
        nxt = []
        for ref, _ in ctx.netlist.nodes(net):
            comp = ctx.netlist.components.get(ref)
            pd = ctx.pdef(comp) if comp else None
            if pd is None or pd.kind == "connector" or ref in chain:
                continue
            others = _nets(ctx, ref) - {net}
            if gnd in others:
                continue  # shunt element (clamp, capacitor)
            nxt.append((ref, pd.kind, others))
        if len(nxt) != 1 or nxt[0][1] not in _SERIES or len(nxt[0][2]) != 1:
            break
        ref, _, others = nxt[0]
        chain.append(ref)
        net = next(iter(others))
    return chain


@rule("protect.structure", "Protection components required by spec.protection are present", PHASE_HARDEN)
def protection(ctx: RuleContext) -> list[Finding]:
    out = []
    spec = ctx.spec
    pos, gnd = spec.power_input.pos_net, spec.ground_net
    req = set(spec.protection)
    if "overcurrent" in req:
        chain = input_chain(ctx)
        fuses = [r for r in chain if ctx.pdef(ctx.netlist.components[r]).kind in ("ptc", "fuse")]
        if not fuses:
            out.append(
                Finding(
                    "protect.overcurrent",
                    Severity.ERROR,
                    f"no fuse/PTC in the series input path from '{pos}'",
                    nets=[pos],
                    hint=f"Insert a PTC in series between '{pos}' and the rest of the circuit "
                    "(before or after a reverse-polarity diode).",
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
