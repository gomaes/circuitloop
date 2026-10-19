"""Through-hole package geometry on a 2.54 mm (0.1") grid.

Offsets are in holes: (dx, dy) with x to the right and y downwards, seen from the
component side. Pad numbers equal the part's pin numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Package:
    name: str
    pads: dict[int, tuple[int, int]]
    body: tuple[tuple[int, int], ...] = ()  # extra cells covered by the body (component side)
    glyph: str = "box"  # drawing style: axial, radial, ecap, led, dip, to92, to220, terminal, header
    height: int = 1  # assembly order: low parts first
    pitch_mm: float = 2.54
    notes: str = ""
    keepout: tuple[tuple[int, int], ...] = field(default=())
    diameter_mm: float = 0.0  # round bodies (drawing only)

    def cells(self) -> set[tuple[int, int]]:
        return set(self.pads.values()) | set(self.body)


def _line(n: int) -> dict[int, tuple[int, int]]:
    return {i + 1: (i, 0) for i in range(n)}


def _span(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((i, 0) for i in range(1, n))


def _disc10() -> tuple[tuple[int, int], ...]:
    """Keep-out for a 10 mm disc centred between pads (0, 0) and (2, 0).

    Radius 2.5 holes (6.35 mm) instead of 1.97: clearance is checked on hole centres only,
    so the margin keeps neighbouring bodies from overlapping between holes.
    """
    return tuple(
        (x, y)
        for x in range(-2, 5)
        for y in range(-3, 4)
        if (x - 1) ** 2 + y**2 <= 6.25 and (x, y) not in ((0, 0), (2, 0))
    )


def _disc(diameter_mm: float, pitch: int) -> tuple[tuple[int, int], ...]:
    """Keep-out of a round body centred between pads (0, 0) and (pitch, 0), with the same margin as
    _disc10 (radius + 1.2 mm, in holes)."""
    r = (diameter_mm / 2 + 1.2) / 2.54
    c = pitch / 2
    n = math.ceil(r) + 1
    return tuple(
        (x, y)
        for x in range(-n, pitch + n + 1)
        for y in range(-n, n + 1)
        if (x - c) ** 2 + y**2 <= r * r and (x, y) not in ((0, 0), (pitch, 0))
    )


def _ecap(name: str, d: float, pitch: int, glyph: str = "ecap") -> Package:
    height = 3 if d <= 6.3 else 4 if d <= 10 else 5
    return Package(name, {1: (0, 0), 2: (pitch, 0)}, _disc(d, pitch), glyph, height, diameter_mm=d)


def _box_film(name: str, pitch: int, width_holes: int = 1) -> Package:
    """Boxed film capacitor: body along the pads, `width_holes` rows thick (row 0 and below)."""
    body = tuple(
        (x, y)
        for x in range(0, pitch + 1)
        for y in range(0, width_holes)
        if (x, y) not in ((0, 0), (pitch, 0))
    )
    return Package(name, {1: (0, 0), 2: (pitch, 0)}, body, "radial", 2)


PACKAGES: dict[str, Package] = {
    "axial_300": Package("axial_300", {1: (0, 0), 2: (3, 0)}, _span(3), "axial", 1),
    "axial_400": Package("axial_400", {1: (0, 0), 2: (4, 0)}, _span(4), "axial", 1),
    "axial_500": Package("axial_500", {1: (0, 0), 2: (5, 0)}, _span(5), "axial", 1),
    "axial_600": Package("axial_600", {1: (0, 0), 2: (6, 0)}, _span(6), "axial", 1),
    # power resistors (2 W / 3 W metal oxide, 5 W cement): mounted a few mm above the board
    "axial_800": Package(
        "axial_800", {1: (0, 0), 2: (8, 0)}, _span(8) + tuple((i, -1) for i in range(1, 8)), "axial", 2
    ),
    "axial_900": Package(
        "axial_900",
        {1: (0, 0), 2: (9, 0)},
        _span(9) + tuple((i, s) for i in range(1, 9) for s in (-1, 1)),
        "axial",
        2,
    ),
    "axial_1100": Package(
        "axial_1100",
        {1: (0, 0), 2: (11, 0)},
        _span(11) + tuple((i, s) for i in range(1, 11) for s in (-1, 1)),
        "axial",
        3,
    ),
    "radial_100": Package("radial_100", {1: (0, 0), 2: (1, 0)}, (), "radial", 2),
    "radial_200": Package("radial_200", {1: (0, 0), 2: (2, 0)}, ((1, 0),), "radial", 2),
    "radial_300": _box_film("radial_300", 3),  # 7.5 mm film box
    "radial_400": _box_film("radial_400", 4, 2),  # 10 mm film box
    "radial_600": _box_film("radial_600", 6, 2),  # 15 mm film box
    # radial electrolytic, 5-6.3 mm diameter: keep the rows above/below free of other parts
    "ecap_d5": Package(
        "ecap_d5", {1: (0, 0), 2: (1, 0)}, ((0, -1), (1, -1), (0, 1), (1, 1), (-1, 0), (2, 0)), "ecap", 3
    ),
    # 10 mm diameter radial parts (electrolytics, power inductors), 5.08 mm pitch
    "ecap_d8": _ecap("ecap_d8", 8.0, 2),
    "ecap_d10": Package("ecap_d10", {1: (0, 0), 2: (2, 0)}, _disc10(), "ecap", 4, diameter_mm=10.0),
    "ecap_d12": _ecap("ecap_d12", 12.5, 2),
    "ecap_d16": _ecap("ecap_d16", 16.0, 3),
    "ecap_d18": _ecap("ecap_d18", 18.0, 3),
    "ind_r8": _ecap("ind_r8", 8.0, 2, "inductor"),
    "ind_r10": Package("ind_r10", {1: (0, 0), 2: (2, 0)}, _disc10(), "inductor", 4, diameter_mm=10.0),
    "ind_r12": _ecap("ind_r12", 12.5, 3, "inductor"),
    "ind_r16": _ecap("ind_r16", 16.0, 3, "inductor"),
    "ind_toroid24": _ecap("ind_toroid24", 24.0, 6, "inductor"),  # vertical toroid on a base plate
    "led_5mm": Package("led_5mm", {1: (0, 0), 2: (1, 0)}, (), "led", 3),
    "led_3mm": Package("led_3mm", {1: (0, 0), 2: (1, 0)}, (), "led", 3),
    "to92": Package("to92", {1: (0, 0), 2: (1, 0), 3: (2, 0)}, (), "to92", 3),
    "to220v": Package("to220v", {1: (0, 0), 2: (1, 0), 3: (2, 0)}, ((0, -1), (1, -1), (2, -1)), "to220", 5),
    "to220_2": Package("to220_2", {1: (0, 0), 2: (2, 0)}, ((1, 0), (0, -1), (1, -1), (2, -1)), "to220", 5),
    # TO-220-5 (1.7 mm staggered leads), leads bent out to a 2-row 2.54 mm pattern
    "to220_5": Package(
        "to220_5",
        {1: (0, 0), 2: (1, 1), 3: (2, 0), 4: (3, 1), 5: (4, 0)},
        tuple((x, -1) for x in range(5)),
        "to220",
        5,
        notes="bend the staggered TO-220-5 leads out to the holes shown",
    ),
    "to126v": Package("to126v", {1: (0, 0), 2: (1, 0), 3: (2, 0)}, ((0, -1), (1, -1), (2, -1)), "to220", 4),
    "dip8": Package(
        "dip8",
        {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (0, 3), 5: (3, 3), 6: (3, 2), 7: (3, 1), 8: (3, 0)},
        tuple((x, y) for x in (1, 2) for y in range(4)),
        "dip",
        2,
        notes="use a DIP-8 socket",
    ),
    "dip14": Package(
        "dip14",
        {**{i + 1: (0, i) for i in range(7)}, **{14 - i: (3, i) for i in range(7)}},
        tuple((x, y) for x in (1, 2) for y in range(7)),
        "dip",
        2,
        notes="use a DIP-14 socket",
    ),
    "bridge_gbu": Package(
        "bridge_gbu",
        {1: (0, 0), 2: (2, 0), 3: (4, 0), 4: (6, 0)},
        tuple((x, -1) for x in range(7)),
        "to220",
        4,
    ),
    "term3_508": Package(
        "term3_508",
        {1: (0, 0), 2: (2, 0), 3: (4, 0)},
        ((1, 0), (3, 0)) + tuple((x, -1) for x in range(5)),
        "terminal",
        4,
    ),
    "term2_508": Package(
        "term2_508", {1: (0, 0), 2: (2, 0)}, ((1, 0), (0, -1), (1, -1), (2, -1)), "terminal", 4
    ),
    "hdr_1x2": Package("hdr_1x2", _line(2), (), "header", 2),
    "hdr_1x3": Package("hdr_1x3", _line(3), (), "header", 2),
    "hdr_1x4": Package("hdr_1x4", _line(4), (), "header", 2),
    "hdr_1x5": Package("hdr_1x5", _line(5), (), "header", 2),
    "hdr_1x6": Package("hdr_1x6", _line(6), (), "header", 2),
    "hdr_1x8": Package("hdr_1x8", _line(8), (), "header", 2),
}


def rotate(dx: int, dy: int, rot: int) -> tuple[int, int]:
    r = rot % 360
    if r == 0:
        return dx, dy
    if r == 90:
        return -dy, dx
    if r == 180:
        return -dx, -dy
    return dy, -dx


def get_package(name: str) -> Package:
    if name not in PACKAGES:
        raise KeyError(f"unknown package '{name}' (known: {', '.join(sorted(PACKAGES))})")
    return PACKAGES[name]
