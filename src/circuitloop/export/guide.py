"""Hand-soldering build guide (Markdown)."""

from __future__ import annotations

from ..layout.board import Layout, hole_name
from ..netlist import Netlist
from ..partsdb import PartsDB

_ORDER_HINT = {
    1: "lowest: resistors and axial diodes (bend leads to the pitch, lie flat)",
    2: "IC sockets, ceramic capacitors, pin headers",
    3: "LEDs and TO-92 parts (observe orientation)",
    4: "terminal blocks",
    5: "tallest: TO-220 regulators",
}


def build_guide(lay: Layout, nl: Netlist, db: PartsDB, title: str, ground: str) -> str:
    x = [f"# Build guide — {title}", ""]
    x += [
        f"Board: **{lay.cols} × {lay.rows} holes** ({lay.cols * 2.54:.1f} × {lay.rows * 2.54:.1f} mm) of 2.54 mm "
        "perfboard with isolated pads (one spare row/column around the circuit is included).",
        "",
        "Hole names: columns **A, B, C …** from the left and rows **1, 2, 3 …** from the top, "
        "as seen from the **component side**. On the solder side the columns run right-to-left; "
        "the solder-side drawing is already mirrored and labelled with the same hole names.",
        "",
        "## 1. Place and solder components (low to high)",
        "",
        "| step | ref | part | value | pins → holes | note |",
        "|---|---|---|---|---|---|",
    ]
    step = 0
    for p in sorted(lay.placed.values(), key=lambda p: (p.pkg.height, p.ref)):
        c = nl.components[p.ref]
        pd = db.resolve(c.part_key, c.value)
        step += 1
        pins = ", ".join(
            f"{pd.pins[n].name if pd else n}→{hole_name(cell)}" for n, cell in sorted(p.pads().items())
        )
        note = []
        if pd and pd.kind in ("electrolytic",):
            note.append("polarised: + to POS")
        if pd and pd.kind in ("diode", "led", "zener", "tvs"):
            note.append("cathode (band / flat) = K")
        if p.pkg.glyph == "dip":
            note.append("socket; pin 1 notch/dot")
        if p.pkg.notes:
            note.append(p.pkg.notes)
        val = c.value if pd and pd.value == "required" else ""
        x.append(f"| {step} | {p.ref} | {c.part_key} | {val} | {pins} | {'; '.join(note)} |")
    x += ["", "Order by height: " + "; ".join(f"{k} = {v}" for k, v in _ORDER_HINT.items()), ""]
    x += [
        "## 2. Solder-side wiring (tinned wire / solder bridges)",
        "",
        "Each run connects the listed holes in a straight line; solder every hole along the run. "
        "Do one net at a time and tick it off.",
        "",
        "| step | net | run (from → to) | holes |",
        "|---|---|---|---|",
    ]
    step = 0
    for t in sorted(lay.traces, key=lambda t: (t.net != ground, t.net)):
        for a, b in t.segments():
            step += 1
            n = abs(a[0] - b[0]) + abs(a[1] - b[1]) + 1
            x.append(f"| {step} | {t.net} | {hole_name(a)} → {hole_name(b)} | {n} |")
    x += ["", "## 3. Insulated jumper wires", ""]
    if lay.jumpers:
        x += [
            "Solder these last, on the solder side, pad to pad, with insulated wire.",
            "",
            "| jumper | net | from | to | approx. length |",
            "|---|---|---|---|---|",
        ]
        for i, j in enumerate(lay.jumpers, 1):
            x.append(f"| W{i} | {j.net} | {hole_name(j.a)} | {hole_name(j.b)} | {j.length_mm + 6:.0f} mm |")
    else:
        x.append("None — every connection is a solder-side run.")
    x += [
        "",
        "## 4. Checks before power-up",
        "",
        "- Inspect every joint; look for bridges between adjacent pads of *different* nets.",
        f"- Continuity: each net below must beep end-to-end; {ground} must **not** beep to any supply net.",
        "",
    ]
    for net in sorted(lay.nets):
        holes = [
            hole_name(lay.placed[r].pads()[int(p)])
            for r, p in nl.nodes(net)
            if r in lay.placed and p.isdigit()
        ]
        x.append(f"  - `{net}`: {', '.join(holes)}")
    x += [
        "",
        "- First power-up through a current-limited supply; check the acceptance voltages from the "
        "verification report.",
    ]
    return "\n".join(x) + "\n"
