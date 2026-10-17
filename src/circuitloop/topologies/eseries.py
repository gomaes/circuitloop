"""IEC 60063 preferred-number series (E6/E12/E24/E96) and value helpers."""

from __future__ import annotations

import math

from ..units import fmt_si

E6 = (1.0, 1.5, 2.2, 3.3, 4.7, 6.8)
E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
E24 = (
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
)  # fmt: skip
E96 = tuple(round(10 ** (i / 96), 2) for i in range(96))
SERIES = {"E6": E6, "E12": E12, "E24": E24, "E96": E96}
# 1 % metal-film resistors are stocked in both E24 and E96 values
E24_E96 = tuple(sorted(set(E24) | set(E96)))


def _values(series: tuple[float, ...], lo: float, hi: float) -> list[float]:
    out = []
    for dec in range(math.floor(math.log10(lo)) - 1, math.ceil(math.log10(hi)) + 1):
        for m in series:
            v = float(f"{m * 10.0**dec:.6g}")
            if lo * (1 - 1e-9) <= v <= hi * (1 + 1e-9):
                out.append(v)
    return sorted(set(out))


def candidates(series: tuple[float, ...], lo: float, hi: float) -> list[float]:
    """All series values in [lo, hi]."""
    return _values(series, lo, hi)


def nearest(x: float, series: tuple[float, ...] = E24_E96) -> float:
    vals = _values(series, x / 20, x * 20)
    return min(vals, key=lambda v: abs(math.log(v / x)))


def ceil_to(x: float, series: tuple[float, ...] = E12) -> float:
    """Smallest series value >= x."""
    return min(v for v in _values(series, x / 20, x * 20) if v >= x * (1 - 1e-9))


def floor_to(x: float, series: tuple[float, ...] = E12) -> float:
    """Largest series value <= x."""
    return max(v for v in _values(series, x / 20, x * 20) if v <= x * (1 + 1e-9))


def fmt_value(x: float) -> str:
    """Value string for part(): 4.7k, 470n, 0.1, 22u."""
    if 0.01 <= x < 1:  # sub-ohm resistors read better as plain numbers
        return f"{x:.3g}"
    s = fmt_si(x, digits=3)
    if s.endswith(".0"):
        s = s[:-2]
    return s
