"""Netlist + parts DB + spec -> ngspice deck.

Every pin of every simulated part is connected through a 0 V "ammeter" source
(``VAM_<ref>_<pin>``) so pin currents, and from them part power, are available
for derating checks regardless of whether the part is a primitive or a
behavioural subcircuit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..netlist import Netlist
from ..partsdb import PartsDB
from ..spec import Fault, Spec
from ..units import parse_value

SRC = "VSRC_IN"


def node_name(net: str, ground: str) -> str:
    if net == ground:
        return "0"
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", net).lower()


def pin_node(ref: str, pin: str | int) -> str:
    return f"p_{ref.lower()}_{pin}"


def ammeter(ref: str, pin: str | int) -> str:
    return f"vam_{ref.lower()}_{pin}"


@dataclass
class Scenario:
    name: str
    vin: float
    fault: Fault | None = None


@dataclass
class Deck:
    text: str
    simulated: list[str] = field(default_factory=list)  # refs with an element in the deck
    connectors: list[str] = field(default_factory=list)
    missing_model: list[str] = field(default_factory=list)
    equivalent: list[tuple[str, str]] = field(default_factory=list)  # (ref, note)
    node_of_net: dict[str, str] = field(default_factory=dict)


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def build_deck(nl: Netlist, db: PartsDB, spec: Spec, sc: Scenario) -> Deck:
    gnd = spec.ground_net
    deck = Deck(text="")
    deck.node_of_net = {n: node_name(n, gnd) for n in nl.nets}
    lines = [f"* circuitloop deck: {spec.name} / {sc.name}", ".options rshunt=1e12 itl1=500 itl4=100"]
    models: dict[str, str] = {}
    body: list[str] = []
    for ref in sorted(nl.components):
        c = nl.components[ref]
        pd = db.get(c.part_key)
        if pd is None or pd.spice is None:
            deck.missing_model.append(ref)
            continue
        if pd.spice.type == "connector":
            deck.connectors.append(ref)
            continue
        if pd.spice.type == "equivalent":
            deck.equivalent.append((ref, pd.spice.note or "equivalent model"))
        value = ""
        if pd.value == "required":
            value = _fmt(parse_value(c.value))

        def sub(m: re.Match, ref=ref, value=value) -> str:
            key = m.group(1)
            if key == "ref":
                return ref
            if key == "value":
                return value
            return pin_node(ref, key)

        body.append(re.sub(r"\{(ref|value|\d+)\}", sub, pd.spice.line or ""))
        for num in sorted(pd.pins):
            net = nl.net_of(ref, num)
            outer = deck.node_of_net[net] if net is not None else f"nc_{ref.lower()}_{num}"
            body.append(f"{ammeter(ref, num).upper()} {outer} {pin_node(ref, num)} 0")
        if pd.spice.models:
            for block in _split_models(pd.spice.models):
                models.setdefault(_model_name(block), block)
        deck.simulated.append(ref)
    lines += list(models.values())
    lines += body
    lines += _harness(spec, sc, deck.node_of_net)
    lines += _control(spec, sc)
    lines.append(".end")
    deck.text = "\n".join(lines) + "\n"
    return deck


def _split_models(text: str) -> list[str]:
    blocks, cur = [], []
    for line in text.strip().splitlines():
        s = line.strip()
        if not s:
            continue
        if cur and not cur[0].lower().startswith(".subckt"):
            blocks.append("\n".join(cur))
            cur = []
        cur.append(s)
        if s.lower().startswith(".ends"):
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _model_name(block: str) -> str:
    first = block.split()
    return f"{first[0].lower()}:{first[1].lower()}" if len(first) > 1 else block


def _load_resistance(spec: Spec, load) -> float:
    if load.resistance is not None:
        return load.resistance
    v = None
    for c in spec.acceptance:
        if getattr(c, "type", "") == "dc_voltage" and c.net == load.net:
            v = (c.min + c.max) / 2
    if v is None:
        v = spec.power_input.v_nom
    return max(v / load.current, 1e-3)


def _harness(spec: Spec, sc: Scenario, nodes: dict[str, str]) -> list[str]:
    gnd = spec.ground_net
    pi = spec.power_input
    vin = sc.vin
    if sc.fault is not None and sc.fault.kind == "reverse_polarity":
        vin = -abs(vin)
    out = [
        "* --- harness ---",
        f"{SRC} src_p 0 DC {_fmt(vin)}",
        f"RSRC_IN src_p {nodes.get(pi.pos_net, node_name(pi.pos_net, gnd))} {_fmt(pi.source_resistance)}",
    ]
    for i, ld in enumerate(spec.loads):
        a = nodes.get(ld.net, node_name(ld.net, gnd))
        b = node_name(ld.ref_net or gnd, gnd)
        if ld.current is not None and sc.fault is None:
            out.append(f"ILOAD_{i} {a} {b} DC {_fmt(ld.current)}")
        else:  # faults use the resistive equivalent so the load cannot force voltages
            out.append(f"RLOAD_{i} {a} {b} {_fmt(_load_resistance(spec, ld))}")
    for i, st in enumerate(spec.stimuli):
        a = nodes.get(st.net, node_name(st.net, gnd))
        b = node_name(st.ref_net or gnd, gnd)
        if st.kind == "dc":
            src = f"DC {_fmt(st.dc)}"
        elif st.kind == "sine":
            src = f"DC {_fmt(st.dc)} SIN({_fmt(st.dc)} {_fmt(st.amplitude)} {_fmt(st.frequency)})"
        else:
            half = 0.5 / st.frequency
            src = (
                f"DC {_fmt(st.dc)} PULSE({_fmt(st.dc)} {_fmt(st.dc + st.amplitude)} 0 "
                f"{_fmt(half / 100)} {_fmt(half / 100)} {_fmt(half * 0.98)} {_fmt(2 * half)})"
            )
        out.append(f"VSTIM_{i} stim_{i} {b} {src}")
        out.append(f"RSTIM_{i} stim_{i} {a} {_fmt(max(st.source_resistance, 1e-3))}")
    return out


def _control(spec: Spec, sc: Scenario) -> list[str]:
    out = [".control", "set filetype=ascii", "op", "write op.raw"]
    if spec.transient is not None:
        # Power-on transient from zero initial conditions (uic): oscillators have
        # no meaningful DC operating point, and start-up is excluded by `settle`.
        t = spec.transient
        out += [f"tran {_fmt(t.step)} {_fmt(t.stop)} 0 {_fmt(t.step)} uic", "write tran.raw"]
    out += [".endc"]
    return out
