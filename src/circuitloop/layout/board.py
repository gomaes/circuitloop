"""Perfboard placement and routing.

Model (2.54 mm perfboard, isolated pads):
- components sit on the component side; their leads occupy holes (pads);
- connections are made on the solder side with tinned wire / solder bridges
  running orthogonally from hole to hole (``Trace``); a hole carries one net;
- where no free path exists, an insulated jumper wire connects two holes of the
  same net (``Jumper``).

Placement: deterministic simulated annealing on half-perimeter wire length.
Routing: A* per net over a minimum spanning order of its pads.
Verification: connectivity is re-extracted from the finished board with
union-find and compared against the netlist (gate G6).
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..results import Finding, GateResult, Severity, status_from
from .packages import Package, get_package, rotate

Cell = tuple[int, int]


@dataclass
class Placed:
    ref: str
    pkg: Package
    x: int
    y: int
    rot: int = 0

    def pads(self) -> dict[int, Cell]:
        out = {}
        for n, (dx, dy) in self.pkg.pads.items():
            rx, ry = rotate(dx, dy, self.rot)
            out[n] = (self.x + rx, self.y + ry)
        return out

    def cells(self) -> set[Cell]:
        out = set(self.pads().values())
        for dx, dy in self.pkg.body:
            rx, ry = rotate(dx, dy, self.rot)
            out.add((self.x + rx, self.y + ry))
        return out


@dataclass
class Trace:
    net: str
    path: list[Cell]

    def segments(self) -> list[tuple[Cell, Cell]]:
        """Straight runs (start, end) along the path."""
        if len(self.path) < 2:
            return []
        segs, start = [], self.path[0]
        prev_dir = None
        for a, b in zip(self.path, self.path[1:], strict=False):
            d = (b[0] - a[0], b[1] - a[1])
            if prev_dir is not None and d != prev_dir:
                segs.append((start, a))
                start = a
            prev_dir = d
        segs.append((start, self.path[-1]))
        return segs


@dataclass
class Jumper:
    net: str
    a: Cell
    b: Cell

    @property
    def length_mm(self) -> float:
        return math.dist(self.a, self.b) * 2.54


@dataclass
class Layout:
    cols: int
    rows: int
    placed: dict[str, Placed]
    pad_net: dict[tuple[str, int], str | None]
    traces: list[Trace] = field(default_factory=list)
    jumpers: list[Jumper] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)

    def pad_cells(self) -> dict[Cell, tuple[str, int]]:
        return {c: (ref, n) for ref, p in self.placed.items() for n, c in p.pads().items()}

    def bbox(self) -> tuple[int, int, int, int]:
        cells = [c for p in self.placed.values() for c in p.cells()]
        cells += [c for t in self.traces for c in t.path]
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        return min(xs), min(ys), max(xs), max(ys)


def hole_name(c: Cell) -> str:
    x, y = c
    s, n = "", x
    while True:
        s = chr(ord("A") + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return f"{s}{y + 1}"


class LayoutError(Exception):
    pass


# ---------------------------------------------------------------- placement
def _nets_for(nl: Netlist, refs: set[str]) -> dict[str, list[tuple[str, int]]]:
    out = {}
    for net, nodes in nl.nets.items():
        pins = [(r, int(p)) for r, p in nodes if r in refs and p.isdigit()]
        if len(pins) >= 2:
            out[net] = pins
    return out


def place(
    nl: Netlist, db: PartsDB, cols: int, rows: int, seed: int = 1, iters_per_part: int = 3000
) -> dict[str, Placed]:
    refs = sorted(nl.components)
    pkgs = {}
    for r in refs:
        pd = db.get(nl.components[r].part_key)
        if pd is None:
            raise LayoutError(f"{r}: not in parts DB")
        pkgs[r] = get_package(pd.package)
    nets = _nets_for(nl, set(refs))
    rng = random.Random(seed)

    # initial shelf packing, biggest first
    order = sorted(refs, key=lambda r: (-len(pkgs[r].cells()), r))
    placed: dict[str, Placed] = {}
    x, y, shelf = 1, 2, 0
    for r in order:
        p = Placed(r, pkgs[r], 0, 0, 0)
        cs = p.cells()
        w = max(c[0] for c in cs) - min(c[0] for c in cs) + 1
        h = max(c[1] for c in cs) - min(c[1] for c in cs) + 1
        if x + w + 1 > cols - 1:
            x, y, shelf = 1, y + shelf + 1, 0
        p.x, p.y = x - min(c[0] for c in cs), y - min(c[1] for c in cs)
        placed[r] = p
        x += w + 1
        shelf = max(shelf, h)

    def cost(pl: dict[str, Placed]) -> float:
        occ: dict[Cell, str] = {}
        pen = 0.0
        for r, p in pl.items():
            for c in p.cells():
                if not (1 <= c[0] < cols - 1 and 1 <= c[1] < rows - 1):
                    pen += 50
                if c in occ:
                    pen += 100
                occ[c] = r
        pads = {r: p.pads() for r, p in pl.items()}
        wl = 0.0
        for pins in nets.values():
            xs = [pads[r][n][0] for r, n in pins]
            ys = [pads[r][n][1] for r, n in pins]
            wl += (max(xs) - min(xs)) + (max(ys) - min(ys))
        allc = list(occ)
        span = (
            max(c[0] for c in allc)
            - min(c[0] for c in allc)
            + max(c[1] for c in allc)
            - min(c[1] for c in allc)
        )
        # discourage pads of different parts touching (leaves room for wiring)
        crowd = 0
        padset = {c: r for r, ps in pads.items() for c in ps.values()}
        for c, r in padset.items():
            for nb in ((c[0] + 1, c[1]), (c[0], c[1] + 1)):
                if nb in padset and padset[nb] != r:
                    crowd += 1
        return wl + 0.5 * span + 0.5 * crowd + pen

    cur = cost(placed)
    best, best_cost = {r: Placed(r, p.pkg, p.x, p.y, p.rot) for r, p in placed.items()}, cur
    n_iter = iters_per_part * len(refs)
    t0 = 4.0
    for i in range(n_iter):
        t = t0 * (1 - i / n_iter) + 0.02
        r = rng.choice(refs)
        p = placed[r]
        old = (p.x, p.y, p.rot)
        move = rng.random()
        swap = None
        if move < 0.6:
            p.x += rng.randint(-3, 3)
            p.y += rng.randint(-3, 3)
        elif move < 0.8:
            p.rot = (p.rot + rng.choice((90, 180, 270))) % 360
        else:
            r2 = rng.choice(refs)
            q = placed[r2]
            swap = (q, (q.x, q.y, q.rot))
            p.x, p.y, q.x, q.y = q.x, q.y, p.x, p.y
        new = cost(placed)
        if new <= cur or rng.random() < math.exp(-(new - cur) / t):
            cur = new
            if cur < best_cost:
                best_cost = cur
                best = {k: Placed(k, v.pkg, v.x, v.y, v.rot) for k, v in placed.items()}
        else:
            p.x, p.y, p.rot = old
            if swap:
                q, (qx, qy, qr) = swap
                q.x, q.y, q.rot = qx, qy, qr
    return best


# ------------------------------------------------------------------ routing
def _astar(starts: set[Cell], goal: Cell, passable, cols: int, rows: int) -> list[Cell] | None:
    def h(c: Cell) -> int:
        return abs(c[0] - goal[0]) + abs(c[1] - goal[1])

    heap = []
    best: dict[tuple[Cell, int], float] = {}
    prev: dict[tuple[Cell, int], tuple[Cell, int] | None] = {}
    for s in sorted(starts):
        key = (s, -1)
        best[key] = 0
        prev[key] = None
        heapq.heappush(heap, (h(s), 0, s, -1))
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    while heap:
        f, g, c, d = heapq.heappop(heap)
        if c == goal:
            path, key = [], (c, d)
            while key is not None:
                path.append(key[0])
                key = prev[key]
            return path[::-1]
        if g > best.get((c, d), math.inf):
            continue
        for k, (dx, dy) in enumerate(dirs):
            n = (c[0] + dx, c[1] + dy)
            if not (0 <= n[0] < cols and 0 <= n[1] < rows):
                continue
            if n != goal and not passable(n):
                continue
            ng = g + 1 + (0.4 if d not in (-1, k) else 0)
            key = (n, k)
            if ng < best.get(key, math.inf):
                best[key] = ng
                prev[key] = (c, d)
                heapq.heappush(heap, (ng + h(n), ng, n, k))
    return None


def route(nl: Netlist, placed: dict[str, Placed], cols: int, rows: int) -> Layout:
    refs = set(placed)
    pad_net: dict[tuple[str, int], str | None] = {}
    cell_owner: dict[Cell, str] = {}
    for r, p in placed.items():
        for n, c in p.pads().items():
            net = nl.net_of(r, n)
            pad_net[(r, n)] = net
            cell_owner[c] = net if net is not None else f"__nc_{r}_{n}"
    nets = _nets_for(nl, refs)
    lay = Layout(cols, rows, placed, pad_net, nets=sorted(nets))

    def hpwl(item) -> int:
        cs = [placed[r].pads()[n] for r, n in item[1]]
        return max(c[0] for c in cs) - min(c[0] for c in cs) + max(c[1] for c in cs) - min(c[1] for c in cs)

    for net, pins in sorted(nets.items(), key=lambda kv: (hpwl(kv), kv[0])):
        cells = [placed[r].pads()[n] for r, n in pins]
        tree = {cells[0]}
        todo = cells[1:]
        while todo:
            todo.sort(key=lambda c: min(abs(c[0] - t[0]) + abs(c[1] - t[1]) for t in tree))
            target = todo.pop(0)
            if target in tree:
                continue

            def passable(c: Cell, net=net) -> bool:
                return cell_owner.get(c) in (None, net)

            path = _astar(tree, target, passable, cols, rows)
            if path is None:
                src = min(tree, key=lambda t: (math.dist(t, target), t))
                lay.jumpers.append(Jumper(net, src, target))
                tree.add(target)
                continue
            for c in path:
                cell_owner[c] = net
                tree.add(c)
            lay.traces.append(Trace(net, path))
    return lay


# ------------------------------------------------------------- verification
class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def verify_layout(lay: Layout, nl: Netlist, max_cols: int, max_rows: int) -> GateResult:
    findings: list[Finding] = []
    occ: dict[Cell, str] = {}
    for r, p in lay.placed.items():
        for c in p.cells():
            if not (0 <= c[0] < lay.cols and 0 <= c[1] < lay.rows):
                findings.append(
                    Finding("layout.bounds", Severity.ERROR, f"{r} is outside the board", refs=[r])
                )
            if c in occ and occ[c] != r:
                findings.append(
                    Finding(
                        "layout.overlap",
                        Severity.ERROR,
                        f"{r} overlaps {occ[c]} at {hole_name(c)}",
                        refs=[r, occ[c]],
                    )
                )
            occ[c] = r
    pads = lay.pad_cells()
    owner: dict[Cell, str] = {}
    for c, (r, n) in pads.items():
        net = lay.pad_net.get((r, n))
        if net is not None:
            owner[c] = net
    uf = _UF()
    for t in lay.traces:
        for c in t.path:
            if c in owner and owner[c] != t.net:
                findings.append(
                    Finding(
                        "layout.short",
                        Severity.ERROR,
                        f"trace of {t.net} touches {owner[c]} at {hole_name(c)}",
                        nets=[t.net],
                    )
                )
            owner.setdefault(c, t.net)
        for a, b in zip(t.path, t.path[1:], strict=False):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                findings.append(
                    Finding("layout.trace", Severity.ERROR, f"non-adjacent trace step in {t.net}")
                )
            uf.union(a, b)
    for j in lay.jumpers:
        uf.union(j.a, j.b)
    # every net's pads in one group; groups never shared between nets
    group_net: dict = {}
    for net, nodes in nl.nets.items():
        cells = [lay.placed[r].pads()[int(p)] for r, p in nodes if r in lay.placed and p.isdigit()]
        roots = {uf.find(c) for c in cells}
        if len(cells) >= 2 and len(roots) != 1:
            findings.append(
                Finding("layout.open", Severity.ERROR, f"net {net} is not fully connected", nets=[net])
            )
        for rt in roots:
            if rt in group_net and group_net[rt] != net:
                findings.append(
                    Finding(
                        "layout.short",
                        Severity.ERROR,
                        f"nets {group_net[rt]} and {net} are shorted",
                        nets=[net, group_net[rt]],
                    )
                )
            group_net[rt] = net
    x0, y0, x1, y1 = lay.bbox()
    w, h = x1 - x0 + 3, y1 - y0 + 3  # one spare hole on every side
    if w > max_cols or h > max_rows:
        findings.append(
            Finding(
                "layout.size",
                Severity.ERROR,
                f"layout needs {w}x{h} holes, spec allows {max_cols}x{max_rows}",
            )
        )
    metrics = {
        "board_holes": [w, h],
        "board_mm": [round(w * 2.54, 1), round(h * 2.54, 1)],
        "traces": len(lay.traces),
        "jumpers": len(lay.jumpers),
        "wire_holes": sum(len(t.path) for t in lay.traces),
    }
    if lay.jumpers:
        findings.append(
            Finding("layout.jumpers", Severity.INFO, f"{len(lay.jumpers)} insulated jumper wire(s)")
        )
    return GateResult("G6", "perfboard layout", status_from(findings), findings, metrics)


def build_layout(
    nl: Netlist, db: PartsDB, max_cols: int, max_rows: int, seeds: tuple[int, ...] = (1, 2, 3, 4)
) -> Layout:
    """Place and route with several deterministic seeds; keep the best board.

    Best = valid placement first, then fewest jumper wires, then smallest area.
    """
    best, best_key = None, None
    for seed in seeds:
        placed = place(nl, db, max_cols, max_rows, seed=seed)
        cand = route(nl, placed, max_cols, max_rows)
        x0, y0, x1, y1 = cand.bbox()
        cells = [c for p in placed.values() for c in p.cells()]
        overlap = len(cells) - len(set(cells))
        outside = sum(not (0 <= c[0] < max_cols and 0 <= c[1] < max_rows) for c in cells)
        key = (overlap + outside, len(cand.jumpers), (x1 - x0 + 1) * (y1 - y0 + 1))
        if best_key is None or key < best_key:
            best, best_key = cand, key
    lay = best
    # normalise: shift so the used area starts at (1, 1)
    x0, y0, x1, y1 = lay.bbox()
    dx, dy = 1 - x0, 1 - y0
    for p in lay.placed.values():
        p.x += dx
        p.y += dy
    for t in lay.traces:
        t.path = [(c[0] + dx, c[1] + dy) for c in t.path]
    for j in lay.jumpers:
        j.a, j.b = (j.a[0] + dx, j.a[1] + dy), (j.b[0] + dx, j.b[1] + dy)
    lay.cols, lay.rows = x1 - x0 + 3, y1 - y0 + 3
    return lay
