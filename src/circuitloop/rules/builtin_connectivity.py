"""Connectivity: unconnected pins, single-node nets, floating inputs, required nets, SKiDL ERC."""

from __future__ import annotations

from . import Finding, RuleContext, Severity, rule


@rule("erc.required_nets", "Nets referenced by the spec exist in the design")
def required_nets(ctx: RuleContext) -> list[Finding]:
    missing = sorted(ctx.spec.required_nets() - set(ctx.netlist.nets))
    return [
        Finding(
            "erc.required_nets",
            Severity.ERROR,
            f"net '{n}' required by spec.yaml is missing",
            nets=[n],
            hint=f'Name the net exactly: Net("{n}")',
        )
        for n in missing
    ]


@rule("erc.unconnected_pin", "Every non-optional pin is connected")
def unconnected(ctx: RuleContext) -> list[Finding]:
    out = []
    for c in sorted(ctx.netlist.components.values(), key=lambda c: c.ref):
        pd = ctx.pdef(c)
        if pd is None:
            continue
        for num, p in sorted(pd.pins.items()):
            if not p.optional and ctx.netlist.net_of(c.ref, num) is None:
                out.append(
                    Finding(
                        "erc.unconnected_pin",
                        Severity.ERROR,
                        f"pin {num} ({p.name}) of {c.ref} is not connected",
                        refs=[c.ref],
                        hint="Unused op-amp sections: tie IN+ to a bias/ground and wire as a follower.",
                    )
                )
    return out


@rule("erc.single_node_net", "No net connects to only one pin (unless it is a spec interface net)")
def single_node(ctx: RuleContext) -> list[Finding]:
    ext = ctx.external_nets()
    return [
        Finding(
            "erc.single_node_net",
            Severity.ERROR,
            f"net '{n}' connects to only {nodes[0][0]} pin {nodes[0][1]}",
            refs=[nodes[0][0]],
            nets=[n],
        )
        for n, nodes in sorted(ctx.netlist.nets.items())
        if len(nodes) == 1 and n not in ext
    ]


@rule("erc.floating_input", "Input pins are driven (not only connected to other inputs)")
def floating_input(ctx: RuleContext) -> list[Finding]:
    out = []
    ext = ctx.external_nets()
    for net, nodes in sorted(ctx.netlist.nets.items()):
        if net in ext:
            continue
        types = []
        for ref, pin in nodes:
            pd = ctx.pdef(ctx.netlist.components[ref]) if ref in ctx.netlist.components else None
            t = pd.pins[int(pin)].type if pd and pin.isdigit() and int(pin) in pd.pins else "passive"
            types.append((ref, pin, t))
        if any(t == "input" for _, _, t in types) and all(t == "input" for _, _, t in types):
            refs = sorted({r for r, _, _ in types})
            out.append(
                Finding(
                    "erc.floating_input",
                    Severity.ERROR,
                    f"net '{net}' only connects input pins ({', '.join(f'{r}.{p}' for r, p, _ in types)})",
                    refs=refs,
                    nets=[net],
                    hint="Drive the input or tie it to a defined level.",
                )
            )
    return out


@rule("erc.shorted_part", "No two-pin part has both pins on the same net")
def shorted(ctx: RuleContext) -> list[Finding]:
    out = []
    for c in ctx.netlist.components.values():
        pd = ctx.pdef(c)
        if pd is None or len(pd.pins) != 2:
            continue
        a, b = (ctx.netlist.net_of(c.ref, n) for n in sorted(pd.pins))
        if a is not None and a == b:
            out.append(
                Finding(
                    "erc.shorted_part",
                    Severity.ERROR,
                    f"{c.ref} has both pins on net '{a}'",
                    refs=[c.ref],
                    nets=[a],
                )
            )
    return out


@rule("erc.skidl", "SKiDL built-in ERC")
def skidl_erc(ctx: RuleContext) -> list[Finding]:
    out, seen = [], set()
    for level, msg in ctx.skidl_erc:
        if (level, msg) in seen:
            continue
        seen.add((level, msg))
        sev = Severity.ERROR if level == "ERROR" else Severity.WARNING
        out.append(Finding("erc.skidl", sev, msg))
    return out
