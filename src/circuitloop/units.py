"""Engineering-notation value parsing/formatting.

Uses electronics conventions (``M`` = mega, ``m`` = milli), never SPICE's
case-insensitive ``M`` = milli. Values are emitted to SPICE as plain floats.
"""

from __future__ import annotations

import math
import re

_SUFFIX = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "m": 1e-3,
    "": 1.0,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
}
_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([pnuµmkKMG]?)\s*([A-Za-zΩ]*)\s*$")
# RKM code, e.g. 4k7, 2R2, 1M5
_RKM = re.compile(r"^\s*(\d+)([RkKM])(\d+)\s*$")


def parse_value(text: str | float | int) -> float:
    if isinstance(text, int | float):
        return float(text)
    m = _RKM.match(text)
    if m:
        mult = {"R": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}[m.group(2)]
        return float(f"{m.group(1)}.{m.group(3)}") * mult
    m = _RE.match(text)
    if not m:
        raise ValueError(f"cannot parse value {text!r}")
    unit = m.group(3)
    if unit and unit.lower() not in ("f", "h", "v", "a", "w", "ohm", "ohms", "r", "hz", "s", "ω"):
        raise ValueError(f"cannot parse value {text!r}")
    return float(m.group(1)) * _SUFFIX[m.group(2)]


def fmt_si(x: float, unit: str = "", digits: int = 3) -> str:
    if x == 0 or not math.isfinite(x):
        return f"{x:g}{unit}"
    exp = int(math.floor(math.log10(abs(x)) / 3) * 3)
    exp = max(-12, min(9, exp))
    prefix = {-12: "p", -9: "n", -6: "u", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}[exp]
    return f"{x / 10**exp:.{digits}g}{prefix}{unit}"
