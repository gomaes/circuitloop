"""Minimal KiCad (E-format) netlist reader -> normalized connectivity model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


class NetlistError(Exception):
    pass


def parse_sexp(text: str) -> list:
    stack: list[list] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            if len(stack) < 2:
                raise NetlistError("unbalanced ')'")
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(tok)
    if len(stack) != 1 or len(stack[0]) != 1:
        raise NetlistError("malformed s-expression")
    return stack[0][0]


def _children(node: list, name: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]


def _value(node: list, name: str) -> str | None:
    for c in _children(node, name):
        return str(c[1]) if len(c) > 1 else ""
    return None


@dataclass
class Component:
    ref: str
    value: str
    footprint: str
    part_key: str | None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Netlist:
    components: dict[str, Component]
    nets: dict[str, list[tuple[str, str]]]  # net name -> [(ref, pin)]

    def __post_init__(self) -> None:
        self.pin_net: dict[tuple[str, str], str] = {}
        for name, nodes in self.nets.items():
            for node in nodes:
                self.pin_net[node] = name

    def net_of(self, ref: str, pin: int | str) -> str | None:
        return self.pin_net.get((ref, str(pin)))

    def nodes(self, net: str) -> list[tuple[str, str]]:
        return self.nets.get(net, [])

    def to_dict(self) -> dict:
        return {
            "components": {
                r: {"value": c.value, "part": c.part_key, "footprint": c.footprint}
                for r, c in sorted(self.components.items())
            },
            "nets": {n: [list(x) for x in v] for n, v in sorted(self.nets.items())},
        }


def read_netlist(path: str | Path) -> Netlist:
    text = Path(path).read_text(encoding="utf-8")
    root = parse_sexp(text)
    if not root or root[0] != "export":
        raise NetlistError("not a KiCad netlist (missing 'export')")
    comps: dict[str, Component] = {}
    for sec in _children(root, "components"):
        for c in _children(sec, "comp"):
            ref = _value(c, "ref") or ""
            fields: dict[str, str] = {}
            for fs in _children(c, "fields"):
                for f in _children(fs, "field"):
                    name = _value(f, "name") or ""
                    vals = [x for x in f[1:] if isinstance(x, str)]
                    fields[name] = vals[-1] if vals else ""
            comps[ref] = Component(
                ref=ref,
                value=_value(c, "value") or "",
                footprint=_value(c, "footprint") or "",
                part_key=fields.get("cloop_part"),
                fields=fields,
            )
    nets: dict[str, list[tuple[str, str]]] = {}
    for sec in _children(root, "nets"):
        for n in _children(sec, "net"):
            name = _value(n, "name") or ""
            nets[name] = [(_value(nd, "ref") or "", _value(nd, "pin") or "") for nd in _children(n, "node")]
    return Netlist(comps, nets)
