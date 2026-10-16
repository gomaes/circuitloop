"""Through-hole package geometry on a 2.54 mm (0.1") grid.

Offsets are in holes: (dx, dy) with x to the right and y downwards, seen from the
component side. Pad numbers equal the part's pin numbers.
"""

from __future__ import annotations

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

    def cells(self) -> set[tuple[int, int]]:
        return set(self.pads.values()) | set(self.body)


def _line(n: int) -> dict[int, tuple[int, int]]:
    return {i + 1: (i, 0) for i in range(n)}


def _span(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((i, 0) for i in range(1, n))


def _disc10() -> tuple[tuple[int, int], ...]:
    """Holes covered by a 10 mm disc centred between pads (0, 0) and (2, 0)."""
    return tuple(
        (x, y)
        for x in range(-1, 4)
        for y in range(-2, 3)
        if (x - 1) ** 2 + y**2 <= 4 and (x, y) not in ((0, 0), (2, 0))
    )


PACKAGES: dict[str, Package] = {
    "axial_300": Package("axial_300", {1: (0, 0), 2: (3, 0)}, _span(3), "axial", 1),
    "axial_400": Package("axial_400", {1: (0, 0), 2: (4, 0)}, _span(4), "axial", 1),
    "axial_500": Package("axial_500", {1: (0, 0), 2: (5, 0)}, _span(5), "axial", 1),
    "axial_600": Package("axial_600", {1: (0, 0), 2: (6, 0)}, _span(6), "axial", 1),
    "radial_100": Package("radial_100", {1: (0, 0), 2: (1, 0)}, (), "radial", 2),
    "radial_200": Package("radial_200", {1: (0, 0), 2: (2, 0)}, ((1, 0),), "radial", 2),
    # radial electrolytic, 5-6.3 mm diameter: keep the rows above/below free of other parts
    "ecap_d5": Package("ecap_d5", {1: (0, 0), 2: (1, 0)}, ((0, -1), (1, -1), (0, 1), (1, 1)), "ecap", 3),
    # 10 mm diameter radial parts (electrolytics, power inductors), 5.08 mm pitch
    "ecap_d10": Package("ecap_d10", {1: (0, 0), 2: (2, 0)}, _disc10(), "ecap", 4),
    "ind_r10": Package("ind_r10", {1: (0, 0), 2: (2, 0)}, _disc10(), "inductor", 4),
    "led_5mm": Package("led_5mm", {1: (0, 0), 2: (1, 0)}, (), "led", 3),
    "to92": Package("to92", {1: (0, 0), 2: (1, 0), 3: (2, 0)}, (), "to92", 3),
    "to220v": Package("to220v", {1: (0, 0), 2: (1, 0), 3: (2, 0)}, ((0, -1), (1, -1), (2, -1)), "to220", 5),
    "dip8": Package(
        "dip8",
        {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (0, 3), 5: (3, 3), 6: (3, 2), 7: (3, 1), 8: (3, 0)},
        tuple((x, y) for x in (1, 2) for y in range(4)),
        "dip",
        2,
        notes="use a DIP-8 socket",
    ),
    "term2_508": Package(
        "term2_508", {1: (0, 0), 2: (2, 0)}, ((1, 0), (0, -1), (1, -1), (2, -1)), "terminal", 4
    ),
    "hdr_1x2": Package("hdr_1x2", _line(2), (), "header", 2),
    "hdr_1x3": Package("hdr_1x3", _line(3), (), "header", 2),
    "hdr_1x4": Package("hdr_1x4", _line(4), (), "header", 2),
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
