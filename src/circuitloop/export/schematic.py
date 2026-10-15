"""Net-label style schematic as SVG.

KiCad schematic files need KiCad's symbol libraries, which are not a dependency
of circuitloop; this renders every part as a symbol whose pins carry net labels
(the same convention as a hierarchical/net-label schematic).
"""

from __future__ import annotations

import html
import re

from ..layout.render import net_color
from ..netlist import Netlist
from ..partsdb import PartsDB

W, PIN = 150, 18


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _natural(ref: str) -> tuple:
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def _symbol(kind: str, cx: float, cy: float) -> str:
    """Small 2-terminal glyph centred at (cx, cy), horizontal."""
    if kind == "resistor":
        pts = " ".join(
            f"{cx - 18 + i * 4.5},{cy + (-5 if i % 2 else 5) if 0 < i < 8 else cy}" for i in range(9)
        )
        return f'<polyline points="{pts}" class="sym"/>'
    if kind in ("capacitor", "electrolytic"):
        s = (
            f'<line x1="{cx - 4}" y1="{cy - 9}" x2="{cx - 4}" y2="{cy + 9}" class="sym"/>'
            f'<line x1="{cx + 4}" y1="{cy - 9}" x2="{cx + 4}" y2="{cy + 9}" class="sym"/>'
        )
        if kind == "electrolytic":
            s += f'<text x="{cx - 14}" y="{cy - 6}" class="pl">+</text>'
        return s
    if kind in ("diode", "led", "zener", "tvs"):
        s = (
            f'<polygon points="{cx - 7},{cy - 8} {cx - 7},{cy + 8} {cx + 7},{cy}" class="sym"/>'
            f'<line x1="{cx + 7}" y1="{cy - 8}" x2="{cx + 7}" y2="{cy + 8}" class="sym"/>'
        )
        if kind == "led":
            s += f'<path d="M{cx + 2},{cy - 10} l6,-6 M{cx + 7},{cy - 10} l6,-6" class="sym"/>'
        return s
    if kind in ("ptc", "fuse"):
        return f'<rect x="{cx - 14}" y="{cy - 5}" width="28" height="10" class="sym"/>'
    return f'<rect x="{cx - 14}" y="{cy - 8}" width="28" height="16" class="sym"/>'


def schematic_svg(nl: Netlist, db: PartsDB, title: str, ground: str = "GND") -> str:
    blocks = []
    for ref in sorted(nl.components, key=_natural):
        c = nl.components[ref]
        pd = db.get(c.part_key)
        pins = sorted(pd.pins.items()) if pd else []
        blocks.append((ref, c, pd, pins))
    cols = 4
    cell_h = []
    for _, _, pd, pins in blocks:
        two = pd is not None and len(pins) == 2 and pd.kind not in ("connector",)
        cell_h.append(70 if two else 40 + PIN * ((len(pins) + 1) // 2))
    rows = [cell_h[i : i + cols] for i in range(0, len(cell_h), cols)]
    row_y = [30]
    for r in rows:
        row_y.append(row_y[-1] + max(r) + 30)
    width = cols * (W + 120) + 40
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {row_y[-1] + 10}" class="sch" '
        f'width="{width}" height="{row_y[-1] + 10}" role="img" aria-label="schematic">',
        "<style>.sch{font-family:ui-sans-serif,system-ui,sans-serif;font-size:11px}"
        ".sym{fill:none;stroke:#222;stroke-width:1.6}.box{fill:#fffbe8;stroke:#222;stroke-width:1.4}"
        ".w{stroke:#222;stroke-width:1.2}.ref{font-weight:700}.val{fill:#555}.pn{fill:#333;font-size:10px}"
        ".nl{font-size:10px;font-weight:600}.pl{font-size:12px;font-weight:700}</style>",
        f'<text x="20" y="18" class="ref">{_e(title)} — net-label schematic</text>',
    ]
    for i, (ref, c, pd, pins) in enumerate(blocks):
        col, row = i % cols, i // cols
        x = 20 + col * (W + 120) + 60
        y = row_y[row]
        kind = pd.kind if pd else "?"
        if pd is not None and len(pins) == 2 and kind != "connector":
            cy = y + 30
            cx = x + W / 2
            (n1, d1), (n2, d2) = pins
            for (n, d), sx, ex in (((n1, d1), x, cx - 20), ((n2, d2), x + W, cx + 20)):
                net = nl.net_of(ref, n) or "NC"
                out.append(f'<line x1="{sx}" y1="{cy}" x2="{ex}" y2="{cy}" class="w"/>')
                anchor = "end" if sx == x else "start"
                lx = sx - 4 if sx == x else sx + 4
                out.append(
                    f'<text x="{lx}" y="{cy + 4}" text-anchor="{anchor}" class="nl" '
                    f'fill="{net_color(net, ground)}">{_e(net)}</text>'
                )
                out.append(
                    f'<text x="{(sx + ex) / 2}" y="{cy - 4}" text-anchor="middle" class="pn">{_e(d.name)}</text>'
                )
            out.append(_symbol(kind, cx, cy))
            out.append(f'<text x="{cx}" y="{cy + 24}" text-anchor="middle" class="ref">{_e(ref)}</text>')
            val = c.value if pd and pd.value == "required" else (pd.key if pd else c.value)
            out.append(f'<text x="{cx}" y="{cy + 36}" text-anchor="middle" class="val">{_e(val)}</text>')
            continue
        half = (len(pins) + 1) // 2
        h = 20 + PIN * half
        out.append(f'<rect x="{x}" y="{y}" width="{W}" height="{h}" class="box"/>')
        out.append(
            f'<text x="{x + W / 2}" y="{y + 14}" text-anchor="middle" class="ref">{_e(ref)} {_e(pd.key if pd else c.value)}</text>'
        )
        for k, (n, d) in enumerate(pins):
            left = k < half
            py = y + 26 + PIN * (k if left else len(pins) - 1 - k)
            net = nl.net_of(ref, n) or "NC"
            if left:
                out.append(f'<line x1="{x - 24}" y1="{py}" x2="{x}" y2="{py}" class="w"/>')
                out.append(f'<text x="{x + 4}" y="{py + 4}" class="pn">{n} {_e(d.name)}</text>')
                out.append(
                    f'<text x="{x - 27}" y="{py + 4}" text-anchor="end" class="nl" fill="{net_color(net, ground)}">{_e(net)}</text>'
                )
            else:
                out.append(f'<line x1="{x + W}" y1="{py}" x2="{x + W + 24}" y2="{py}" class="w"/>')
                out.append(
                    f'<text x="{x + W - 4}" y="{py + 4}" text-anchor="end" class="pn">{_e(d.name)} {n}</text>'
                )
                out.append(
                    f'<text x="{x + W + 27}" y="{py + 4}" class="nl" fill="{net_color(net, ground)}">{_e(net)}</text>'
                )
    out.append("</svg>")
    return "\n".join(out)
