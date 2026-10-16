"""Render the parts DB as a Markdown catalog for agents."""

from __future__ import annotations

from .partsdb import PartsDB
from .units import fmt_si


def render_catalog(db: PartsDB) -> str:
    lines = [
        "# Parts catalog",
        "",
        'Only these parts may be used: `part("<KEY>", value, ref=...)`.',
        'Pins are listed as `number:NAME`; address them by name (`u1["VCC"]`) or number.',
        "Ratings are absolute maximums; the spec's derating factors apply in normal operation.",
        "",
    ]
    by_kind: dict[str, list] = {}
    for k in db.keys():
        by_kind.setdefault(db[k].kind, []).append(db[k])
    for kind in sorted(by_kind):
        lines += [f"## {kind}", ""]
        for p in by_kind[kind]:
            pins = ", ".join(
                f"{n}:{d.name}"
                + (f" ({d.type})" if d.type != "passive" else "")
                + (" [optional]" if d.optional else "")
                for n, d in sorted(p.pins.items())
            )
            rat = []
            for r in p.ratings:
                if r.type == "voltage":
                    rng = f"{r.lower:g}..{r.max:g} V"
                    rat.append(f"V(pin{r.pins[0]},pin{r.pins[1]}) {rng}")
                elif r.type == "current":
                    rat.append(f"|I(pin{r.pin})| <= {fmt_si(r.max, 'A')}")
                else:
                    rat.append(f"P <= {fmt_si(r.max, 'W')}")
            lines.append(f"### `{p.key}`")
            lines.append(f"- {p.description}")
            val = "REQUIRED" if p.value == "required" else "fixed"
            if p.value == "required" and (p.value_min or p.value_max):
                val += f" ({fmt_si(p.value_min or 0)}..{fmt_si(p.value_max) if p.value_max else 'any'})"
            if p.tolerance:
                val += f", tolerance ±{p.tolerance:.0%}"
            lines.append(f"- package: {p.package}; value: {val}")
            if p.spice and p.spice.params:
                prm = "; ".join(f"{n} = {v.value:g} ±{v.tolerance:.0%}" for n, v in p.spice.params.items())
                lines.append(f"- model parameters (with tolerance): {prm}")
            lines.append(f"- pins: {pins}")
            lines.append(f"- ratings: {'; '.join(rat)}")
            if p.decoupling:
                dec = "; ".join(
                    f">= {fmt_si(d.min, 'F')} between pin {d.pin} ({p.pins[d.pin].name}) and pin {d.gnd} "
                    f"({p.pins[d.gnd].name})"
                    for d in p.decoupling
                )
                lines.append(f"- required decoupling: {dec}")
            if p.spice is None:
                lines.append("- WARNING: no SPICE model (simulation would be incomplete)")
            elif p.spice.type == "equivalent":
                lines.append(f"- simulated with an equivalent model: {p.spice.note or ''}")
            lines.append("")
    return "\n".join(lines)
