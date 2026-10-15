"""Bill of materials (CSV) from the netlist + parts DB."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..units import fmt_si


def _natural(ref: str) -> tuple:
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def _ratings(pd) -> str:
    parts = []
    for r in pd.ratings:
        if r.type == "power":
            parts.append(f"{fmt_si(r.max, 'W')}")
        elif r.type == "voltage":
            parts.append(f"{r.max:g}V")
        else:
            parts.append(f"{fmt_si(r.max, 'A')}")
    return " / ".join(parts)


def bom_rows(nl: Netlist, db: PartsDB) -> list[dict]:
    groups: dict[tuple[str, str], list[str]] = {}
    for ref, c in nl.components.items():
        groups.setdefault((c.part_key or "?", c.value), []).append(ref)
    rows = []
    for (key, value), refs in sorted(groups.items(), key=lambda kv: _natural(sorted(kv[1], key=_natural)[0])):
        pd = db.get(key)
        refs = sorted(refs, key=_natural)
        rows.append(
            {
                "refs": " ".join(refs),
                "qty": len(refs),
                "part": key,
                "value": value if pd is None or pd.value == "required" else "",
                "mpn": pd.mpn_for(value) if pd else "",
                "description": pd.description if pd else "UNREGISTERED",
                "package": pd.package if pd else "",
                "footprint": pd.footprint if pd else "",
                "ratings": _ratings(pd) if pd else "",
            }
        )
    return rows


def write_bom(nl: Netlist, db: PartsDB, path: Path) -> list[dict]:
    rows = bom_rows(nl, db)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["refs"])
        w.writeheader()
        w.writerows(rows)
    return rows
