"""Collects parts and connections and renders them as a design.py."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

from ..partsdb import REF_PREFIX, PartsDB, check_value


class TopologyError(Exception):
    """The topology cannot meet the spec with the registered parts (message explains why)."""


@dataclass
class Placed:
    ref: str
    key: str
    value: str | None
    comment: str


@dataclass
class DesignWriter:
    db: PartsDB
    parts: list[Placed] = field(default_factory=list)
    nets: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    net_comments: dict[str, str] = field(default_factory=dict)
    _used: dict[tuple[str, str], str] = field(default_factory=dict)

    def add(self, key: str, value: str | None = None, comment: str = "") -> str:
        """Place a registered part; returns its reference designator."""
        pd = self.db.get(key)
        if pd is None:
            raise TopologyError(f"part '{key}' is not in the parts DB")
        msg = check_value(pd, value)
        if msg:
            raise TopologyError(msg)
        prefix = REF_PREFIX[pd.kind]
        n = 1 + sum(1 for p in self.parts if p.ref.rstrip("0123456789") == prefix)
        ref = f"{prefix}{n}"
        self.parts.append(Placed(ref, key, value, comment))
        return ref

    def key_of(self, ref: str) -> str:
        return next(p.key for p in self.parts if p.ref == ref)

    def connect(self, net: str, *pins: str, comment: str = "") -> None:
        """Connect pins given as "U1.IN" / "J1.1" to a net."""
        for spec in pins:
            ref, _, pin = spec.partition(".")
            pd = self.db[self.key_of(ref)]
            num = pd.pin_by_name(pin)
            if num is None and pin.isdigit() and int(pin) in pd.pins:
                num = int(pin)
            if num is None:
                raise TopologyError(f"{ref} ({pd.key}) has no pin '{pin}'")
            k = (ref, str(num))
            if k in self._used and self._used[k] != net:
                raise TopologyError(f"{spec} is already connected to {self._used[k]}")
            self._used[k] = net
            self.nets.setdefault(net, []).append((ref, pin))
        if comment:
            self.net_comments[net] = comment

    # ------------------------------------------------------------- rendering
    def render(self, docstring: str) -> str:
        var = {p.ref: p.ref.lower() for p in self.parts}
        taken = set(var.values()) | {"part", "finish", "net"}
        nvar: dict[str, str] = {}
        for net in self.nets:
            v = re.sub(r"\W", "_", net.lower())
            if not v or v[0].isdigit():
                v = "n_" + v
            while v in taken or keyword.iskeyword(v) or v in nvar.values():
                v += "_net"
            nvar[net] = v
        lines = ['"""' + docstring.strip() + '\n"""', "", "from circuitloop.lib import Net, finish, part", ""]
        names = list(self.nets)
        for i in range(0, len(names), 4):
            chunk = names[i : i + 4]
            lines.append(", ".join(nvar[n] for n in chunk) + " = " + ", ".join(f'Net("{n}")' for n in chunk))
        lines.append("")
        for p in self.parts:
            args = [f'"{p.key}"'] + ([f'"{p.value}"'] if p.value is not None else []) + [f'ref="{p.ref}"']
            line = f"{var[p.ref]} = part({', '.join(args)})"
            lines.append(line + (f"  # {p.comment}" if p.comment else ""))
        lines.append("")
        for net, pins in self.nets.items():
            terms = []
            for ref, pin in pins:
                terms.append(f"{var[ref]}[{pin}]" if pin.isdigit() else f'{var[ref]}["{pin}"]')
            line = f"{nvar[net]} += {', '.join(terms)}"
            lines.append(line + (f"  # {self.net_comments[net]}" if net in self.net_comments else ""))
        lines += ["", "finish()", ""]
        return "\n".join(lines)
