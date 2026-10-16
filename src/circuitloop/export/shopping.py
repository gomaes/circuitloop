"""Shopping list: everything needed to build N boards (components + build materials)."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from ..netlist import Netlist
from ..partsdb import PartsDB
from .bom import bom_rows


@dataclass
class Item:
    category: str  # component | socket | board | wire
    name: str
    value: str
    qty: float
    unit: str
    mpn: str
    note: str = ""
    description: str = ""


def _short(text: str, n: int = 70) -> str:
    first = text.split(". ")[0].strip()
    return first if len(first) <= n else first[: n - 1] + "…"


def _spare(qty: int, kind: str, spares: float) -> int:
    """Extra pieces for cheap, easily lost parts (resistors, capacitors) when spares > 0."""
    if spares <= 0 or kind not in ("resistor", "capacitor", "electrolytic", "led", "diode"):
        return qty
    return qty + max(1, math.ceil(qty * spares))


def shopping_items(
    nl: Netlist, db: PartsDB, layout: dict | None = None, boards: int = 1, spares: float = 0.0
) -> list[Item]:
    items: list[Item] = []
    for row in bom_rows(nl, db):
        pd = db.get(row["part"])
        qty = _spare(row["qty"] * boards, pd.kind if pd else "", spares)
        items.append(
            Item(
                "component",
                row["part"],
                str(row["value"]),
                qty,
                "pcs",
                row["mpn"],
                row["refs"],
                _short(row["description"]),
            )
        )
    # IC sockets for DIP packages (the build guide solders sockets, not the ICs)
    dips: dict[str, int] = {}
    for c in nl.components.values():
        pd = db.get(c.part_key)
        if pd and pd.package.startswith("dip"):
            dips[pd.package] = dips.get(pd.package, 0) + 1
    for pkg, n in sorted(dips.items()):
        pins = pkg[3:]
        items.append(
            Item(
                "socket",
                f"DIP-{pins} IC socket",
                "",
                n * boards,
                "pcs",
                f"DIP-{pins} socket 2.54mm",
                "solder the socket, then insert the IC",
            )
        )
    if layout:
        cols, rows = layout["cols"], layout["rows"]
        items.append(
            Item(
                "board",
                "Universal perfboard (isolated pads, 2.54 mm)",
                f"{cols}x{rows} holes",
                boards,
                "pcs",
                "",
                f"cut size at least {cols * 2.54:.0f} x {rows * 2.54:.0f} mm",
            )
        )
        tinned = sum(
            (abs(a[0] - b[0]) + abs(a[1] - b[1])) * 2.54
            for t in layout.get("traces", [])
            for a, b in zip(t["path"], t["path"][1:], strict=False)
        )
        if tinned:
            items.append(
                Item(
                    "wire",
                    "Tinned copper wire (solder-side runs)",
                    "0.5-0.6 mm",
                    round(tinned * 1.3 * boards / 1000, 2),
                    "m",
                    "",
                    "includes 30 % margin",
                )
            )
        jumpers = layout.get("jumpers", [])
        if jumpers:
            total = sum(math.dist(j["a"], j["b"]) * 2.54 + 10 for j in jumpers)
            items.append(
                Item(
                    "wire",
                    "Insulated hook-up wire (jumpers)",
                    "AWG24-26",
                    round(total * 1.3 * boards / 1000, 2),
                    "m",
                    "",
                    f"{len(jumpers) * boards} jumper(s)",
                )
            )
    return items


def write_shopping_list(items: list[Item], out_dir: Path, title: str, boards: int = 1) -> tuple[Path, Path]:
    csv_path = out_dir / "shopping_list.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(items[0]).keys()) if items else ["name"])
        w.writeheader()
        for it in items:
            w.writerow(asdict(it))
    lines = [
        f"# Shopping list — {title}",
        "",
        f"Quantities for **{boards} board(s)**.",
        "",
        "| category | item | value | qty | unit | part number | refs / note | description |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for it in items:
        qty = f"{it.qty:g}"
        lines.append(
            f"| {it.category} | {it.name} | {it.value} | {qty} | {it.unit} | {it.mpn} | {it.note} | {it.description} |"
        )
    lines += ["", "Also needed: solder, flux, and hook-up wire for the external connections."]
    md_path = out_dir / "shopping_list.md"
    md_path.write_text("\n".join(lines) + "\n")
    return csv_path, md_path


def load_layout(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
