"""SVG / HTML rendering of a perfboard layout (component side and solder side)."""

from __future__ import annotations

import hashlib
import html
import math

from ..netlist import Netlist
from ..partsdb import PartsDB
from .board import Cell, Layout, Placed, hole_name

S = 24  # px per hole
M = 28  # margin for coordinate labels

_FIXED = {"GND": "#3b3b3b", "0": "#3b3b3b"}
_PALETTE = [
    "#d1495b",
    "#2e86ab",
    "#3fa34d",
    "#e07a1f",
    "#8e44ad",
    "#16a085",
    "#c0392b",
    "#2c3e50",
    "#b8860b",
    "#1f618d",
    "#7d3c98",
    "#117a65",
    "#a04000",
    "#5d6d7e",
]


def net_color(net: str | None, ground: str = "GND") -> str:
    if net is None:
        return "#999999"
    if net == ground or net in _FIXED:
        return _FIXED.get(net, "#3b3b3b")
    h = int(hashlib.sha1(net.encode()).hexdigest(), 16)
    return _PALETTE[h % len(_PALETTE)]


def _xy(c: Cell, cols: int, mirror: bool) -> tuple[float, float]:
    x = (cols - 1 - c[0]) if mirror else c[0]
    return M + x * S + S / 2, M + c[1] * S + S / 2


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _frame(lay: Layout, mirror: bool, title: str) -> list[str]:
    w, h = lay.cols * S + 2 * M, lay.rows * S + 2 * M
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h + 22}" width="{w}" height="{h + 22}" '
        f'class="board" role="img" aria-label="{_esc(title)}">',
        f'<text x="{M}" y="{h + 16}" class="cap">{_esc(title)}</text>',
        f'<rect x="{M - 6}" y="{M - 6}" width="{lay.cols * S + 12}" height="{lay.rows * S + 12}" rx="6" class="pcb"/>',
    ]
    for col in range(lay.cols):
        x, _ = _xy((col, 0), lay.cols, mirror)
        out.append(
            f'<text x="{x}" y="{M - 10}" class="lbl" text-anchor="middle">{hole_name((col, 0))[:-1]}</text>'
        )
    for row in range(lay.rows):
        _, y = _xy((0, row), lay.cols, mirror)
        out.append(f'<text x="{M - 12}" y="{y + 4}" class="lbl" text-anchor="end">{row + 1}</text>')
    for col in range(lay.cols):
        for row in range(lay.rows):
            x, y = _xy((col, row), lay.cols, mirror)
            out.append(
                f'<circle cx="{x}" cy="{y}" r="{S * 0.32:.1f}" class="ring"/>'
                f'<circle cx="{x}" cy="{y}" r="{S * 0.13:.1f}" class="hole"/>'
            )
    return out


def _body(p: Placed, lay: Layout, kind: str, value: str) -> list[str]:
    pads = p.pads()
    pts = [_xy(c, lay.cols, False) for c in p.cells()]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    x0, x1, y0, y1 = min(xs) - S * 0.42, max(xs) + S * 0.42, min(ys) - S * 0.42, max(ys) + S * 0.42
    g = p.pkg.glyph
    tip = _esc(
        f"{p.ref} {value} ({kind}) — "
        + ", ".join(f"pin {n}: {hole_name(c)}" for n, c in sorted(pads.items()))
    )
    out = [f'<g class="part"><title>{tip}</title>']
    if g in ("axial",):
        a, b = _xy(pads[1], lay.cols, False), _xy(pads[2], lay.cols, False)
        out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" class="lead"/>')
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        L = math.dist(a, b) * 0.55
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        cls = "res" if kind == "resistor" else "dio"
        out.append(
            f'<g transform="translate({cx},{cy}) rotate({ang})">'
            f'<rect x="{-L / 2}" y="{-S * 0.28}" width="{L}" height="{S * 0.56}" rx="{S * 0.2}" class="{cls}"/>'
        )
        if cls == "dio":  # cathode band at pin 2 side
            out.append(
                f'<rect x="{L / 2 - S * 0.25}" y="{-S * 0.28}" width="{S * 0.14}" height="{S * 0.56}" class="band"/>'
            )
        out.append("</g>")
    elif g in ("radial", "led") or kind == "electrolytic":
        a, b = _xy(pads[1], lay.cols, False), _xy(pads[2], lay.cols, False)
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        r = max(math.dist(a, b) / 2 + S * 0.38, S * 0.75)
        cls = {"led": "led", "radial": "ecap" if kind == "electrolytic" else "cer"}.get(g, "cer")
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" class="{cls}"/>')
        if kind in ("electrolytic", "led"):
            out.append(f'<text x="{a[0]}" y="{a[1] - S * 0.45}" class="pol" text-anchor="middle">+</text>')
    elif g == "dip":
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="3" class="ic"/>')
        p1 = _xy(pads[1], lay.cols, False)
        out.append(f'<circle cx="{p1[0] + S * 0.55}" cy="{p1[1]}" r="{S * 0.14}" class="dot"/>')
    elif g == "to220":
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="2" class="ic"/>')
    elif g == "to92":
        out.append(
            f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{S * 0.45}" class="ic"/>'
        )
    elif g == "terminal":
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="2" class="term"/>')
    else:  # header / box
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="2" class="hdr"/>')
    for n, c in pads.items():
        x, y = _xy(c, lay.cols, False)
        out.append(f'<circle cx="{x}" cy="{y}" r="{S * 0.2:.1f}" class="pin{" pin1" if n == 1 else ""}"/>')
    label = p.ref if kind in ("connector",) else f"{p.ref}"
    out.append(
        f'<text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 + 4}" class="ref" text-anchor="middle">{_esc(label)}</text>'
    )
    out.append("</g>")
    return out


def component_side_svg(lay: Layout, nl: Netlist, db: PartsDB, title: str) -> str:
    out = _frame(lay, False, f"{title} — component side (top view)")
    order = sorted(lay.placed.values(), key=lambda p: p.pkg.height)
    for p in order:
        c = nl.components[p.ref]
        pd = db.get(c.part_key)
        out += _body(p, lay, pd.kind if pd else "?", c.value)
    out.append("</svg>")
    return "\n".join(out)


def solder_side_svg(lay: Layout, ground: str, title: str) -> str:
    out = _frame(lay, True, f"{title} — solder side (board flipped left-to-right)")
    for t in lay.traces:
        col = net_color(t.net, ground)
        pts = " ".join(f"{_xy(c, lay.cols, True)[0]},{_xy(c, lay.cols, True)[1]}" for c in t.path)
        segs = "; ".join(f"{hole_name(a)}→{hole_name(b)}" for a, b in t.segments())
        out.append(
            f'<polyline points="{pts}" class="trace" stroke="{col}"><title>{_esc(t.net)}: {segs}</title></polyline>'
        )
    for (ref, n), net in sorted(lay.pad_net.items()):
        c = lay.placed[ref].pads()[n]
        x, y = _xy(c, lay.cols, True)
        out.append(
            f'<circle cx="{x}" cy="{y}" r="{S * 0.3:.1f}" class="pad" fill="{net_color(net, ground)}">'
            f"<title>{_esc(ref)} pin {n} — {_esc(net or 'not connected')} ({hole_name(c)})</title></circle>"
        )
    for i, j in enumerate(lay.jumpers, 1):
        a, b = _xy(j.a, lay.cols, True), _xy(j.b, lay.cols, True)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - S * 0.8
        out.append(
            f'<path d="M{a[0]},{a[1]} Q{mx},{my} {b[0]},{b[1]}" class="jumper" stroke="{net_color(j.net, ground)}">'
            f"<title>jumper W{i}: {_esc(j.net)} {hole_name(j.a)}↔{hole_name(j.b)}</title></path>"
        )
        out.append(f'<text x="{mx}" y="{my + 2}" class="jl" text-anchor="middle">W{i}</text>')
    out.append("</svg>")
    return "\n".join(out)


SVG_STYLE = """
.board{max-width:100%;height:auto;font-family:ui-sans-serif,system-ui,sans-serif}
.pcb{fill:#d8b77a;stroke:#9c7a3c;stroke-width:2}
.ring{fill:#e7c992;stroke:#b08a4a;stroke-width:1}.hole{fill:#5a4520}
.lbl{font-size:9px;fill:#5b4a2a}.cap{font-size:12px;fill:currentColor}
.lead{stroke:#8a8a8a;stroke-width:2}.res{fill:#e8d2a6;stroke:#7b5e2a}.dio{fill:#333;stroke:#111}
.band{fill:#ddd}.cer{fill:#e5a33a;stroke:#8a5a10}.ecap{fill:#2f4d80;stroke:#16264a}
.led{fill:#e23b3b;fill-opacity:.75;stroke:#7a1010}.ic{fill:#2a2a2a;stroke:#000}
.term{fill:#2a9d4a;stroke:#145a28}.hdr{fill:#222;stroke:#000}
.pin{fill:#c0c0c0;stroke:#555}.pin1{fill:#ffd24a}.dot{fill:#ddd}
.ref{font-size:10px;font-weight:700;fill:#fff;paint-order:stroke;stroke:#000;stroke-width:2.5px}
.pol{font-size:12px;font-weight:700;fill:#fff;paint-order:stroke;stroke:#000;stroke-width:2px}
.trace{fill:none;stroke-width:7;stroke-linecap:round;stroke-linejoin:round;opacity:.9}
.pad{stroke:#333;stroke-width:1}
.jumper{fill:none;stroke-width:3;stroke-dasharray:6 3}
.jl{font-size:10px;font-weight:700;fill:#000;paint-order:stroke;stroke:#fff;stroke-width:3px}
"""


def standalone_svg(svg: str) -> str:
    return svg.replace(">", f"><style>{SVG_STYLE}</style>", 1)
