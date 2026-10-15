"""Decoupling capacitors required by the parts DB (per IC power pin)."""

from __future__ import annotations

from ..units import fmt_si
from . import Finding, RuleContext, Severity, rule


@rule("erc.decoupling", "Each IC power pin listed in the parts DB has enough capacitance to its ground pin")
def decoupling(ctx: RuleContext) -> list[Finding]:
    out = []
    caps = ctx.components_of_kind("capacitor", "electrolytic")
    for c in sorted(ctx.netlist.components.values(), key=lambda c: c.ref):
        pd = ctx.pdef(c)
        if pd is None:
            continue
        for d in pd.decoupling:
            vnet, gnet = ctx.netlist.net_of(c.ref, d.pin), ctx.netlist.net_of(c.ref, d.gnd)
            if vnet is None or gnet is None or vnet == gnet:
                continue  # reported by connectivity rules
            total = 0.0
            for cap in caps:
                nets = {ctx.netlist.net_of(cap.ref, 1), ctx.netlist.net_of(cap.ref, 2)}
                if nets == {vnet, gnet}:
                    total += ctx.value(cap) or 0.0
            if total < d.min:
                out.append(
                    Finding(
                        "erc.decoupling",
                        Severity.ERROR,
                        f"{c.ref} pin {d.pin} ({pd.pins[d.pin].name}) needs >= {fmt_si(d.min, 'F')} to "
                        f"pin {d.gnd} ({pd.pins[d.gnd].name}); found {fmt_si(total, 'F')}",
                        refs=[c.ref],
                        nets=[vnet, gnet],
                        hint=f"Add a capacitor between nets '{vnet}' and '{gnet}' close to {c.ref}.",
                    )
                )
    return out
