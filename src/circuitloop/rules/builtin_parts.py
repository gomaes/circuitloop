"""Parts must be registered in the parts DB, match its pinout and obey the spec's parts policy."""

from __future__ import annotations

from ..partsdb import check_value
from . import Finding, RuleContext, Severity, rule


@rule("erc.registered_part", "Every component is registered in the parts DB with a matching pinout")
def registered(ctx: RuleContext) -> list[Finding]:
    out = []
    used_pins: dict[str, set[str]] = {}
    for ref, pin in ctx.netlist.pin_net:
        used_pins.setdefault(ref, set()).add(pin)
    for c in sorted(ctx.netlist.components.values(), key=lambda c: c.ref):
        pd = ctx.pdef(c)
        if pd is None:
            out.append(
                Finding(
                    "erc.registered_part",
                    Severity.ERROR,
                    f"{c.ref} ('{c.part_key or c.value}') is not in the parts DB; ratings cannot be checked",
                    refs=[c.ref],
                    hint="Use part('<KEY>') with a key from the parts catalog.",
                )
            )
            continue
        bad = sorted(p for p in used_pins.get(c.ref, set()) if not p.isdigit() or int(p) not in pd.pins)
        if bad:
            out.append(
                Finding(
                    "erc.registered_part",
                    Severity.ERROR,
                    f"{c.ref} uses pins {bad} that {pd.key} does not have",
                    refs=[c.ref],
                )
            )
        msg = check_value(pd, c.value if pd.value == "required" else None)
        if msg:
            out.append(Finding("erc.value", Severity.ERROR, f"{c.ref}: {msg}", refs=[c.ref]))
    return out


@rule("erc.parts_policy", "Parts obey spec.parts_policy (through-hole only, forbidden list)")
def policy(ctx: RuleContext) -> list[Finding]:
    out = []
    pol = ctx.spec.parts_policy
    for c in ctx.netlist.components.values():
        pd = ctx.pdef(c)
        if pd is None:
            continue
        if pol.tht_only and pd.mount != "tht":
            out.append(
                Finding(
                    "erc.parts_policy",
                    Severity.ERROR,
                    f"{c.ref} ({pd.key}) is not through-hole",
                    refs=[c.ref],
                )
            )
        if pd.key in pol.forbidden:
            out.append(
                Finding(
                    "erc.parts_policy", Severity.ERROR, f"{c.ref} uses forbidden part {pd.key}", refs=[c.ref]
                )
            )
    return out
