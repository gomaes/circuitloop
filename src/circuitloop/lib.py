"""Design-side API imported by ``design.py``.

    from circuitloop.lib import Net, part, finish

    vin, gnd = Net("VIN"), Net("GND")
    r1 = part("R_1/4W", "1k")
    vin += r1[1]
    finish()

Parts are instantiated from the parts DB so pinouts and footprints are never
invented by the design author. ``finish()`` runs SKiDL's ERC and writes the KiCad
netlist to the path given by ``$CLOOP_NETLIST`` (default ``circuit.net``).
"""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

from skidl import ERC, POWER, SKIDL, Net, Part, Pin, generate_netlist

from .partsdb import PartsDB, check_value, load_db

__all__ = ["Net", "part", "finish", "parts_db"]

_PIN_FUNC = {
    "passive": Pin.types.PASSIVE,
    "input": Pin.types.INPUT,
    "output": Pin.types.OUTPUT,
    "power_in": Pin.types.PWRIN,
    "power_out": Pin.types.PWROUT,
    "bidirectional": Pin.types.BIDIR,
}
_PREFIX = {
    "resistor": "R",
    "capacitor": "C",
    "electrolytic": "C",
    "diode": "D",
    "zener": "D",
    "tvs": "D",
    "led": "D",
    "transistor": "Q",
    "mosfet": "Q",
    "regulator": "U",
    "ic": "U",
    "opamp": "U",
    "ptc": "F",
    "fuse": "F",
    "connector": "J",
}
_db: PartsDB | None = None


def parts_db() -> PartsDB:
    global _db
    if _db is None:
        project = os.environ.get("CLOOP_PROJECT_DIR")
        _db = load_db(Path(project) if project else Path.cwd())
    return _db


def part(key: str, value: str | float | None = None, ref: str | None = None) -> Part:
    """Instantiate a registered part. ``value`` is required for R/C families."""
    db = parts_db()
    if key not in db:
        raise KeyError(f"part '{key}' is not in the parts DB (see `cloop parts list`)")
    pd = db[key]
    val = None if value is None else str(value)
    msg = check_value(pd, val)
    if msg:
        raise ValueError(msg)
    kwargs = {}
    if ref:
        kwargs["ref"] = ref
    p = Part(
        tool=SKIDL,
        name=key,
        ref_prefix=_PREFIX[pd.kind],
        value=val if val is not None else key,
        footprint=pd.footprint,
        pins=[Pin(num=n, name=pdef.name, func=_PIN_FUNC[pdef.type]) for n, pdef in pd.pins.items()],
        **kwargs,
    )
    p.tag = p.ref
    p.fields["cloop_part"] = key
    return p


def finish() -> None:
    """Run SKiDL ERC and write the netlist. Call once at the end of design.py."""
    circuit = builtins.default_circuit  # SKiDL installs its default circuit here
    power = {n for n in os.environ.get("CLOOP_POWER_NETS", "").split(",") if n}
    for net in circuit.nets:
        if net.name in power:
            net.drive = POWER
    for p in circuit.parts:
        p.tag = p.ref
    ERC()
    out = os.environ.get("CLOOP_NETLIST", "circuit.net")
    generate_netlist(file_=out)
    print("CLOOP_FINISH_OK", file=sys.stderr)
