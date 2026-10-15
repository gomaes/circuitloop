"""Pluggable ERC rules.

A rule is a function ``(ctx: RuleContext) -> list[Finding]`` registered with
:func:`rule`. Rules are collected from:

1. built-in modules in this package,
2. the ``circuitloop.rules`` entry-point group (installed plugins),
3. ``*.py`` files in ``<project>/rules/`` (hashed and read-only to agents).

Example project rule (``rules/no_big_resistors.py``)::

    from circuitloop.rules import rule, Finding, Severity

    @rule("project.no_big_r", "Resistors above 1M are not stocked")
    def check(ctx):
        return [Finding("project.no_big_r", Severity.ERROR, f"{c.ref} too large", refs=[c.ref])
                for c in ctx.components_of_kind("resistor") if ctx.value(c) > 1e6]
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path

from ..netlist import Component, Netlist
from ..partsdb import PartDef, PartsDB
from ..results import Finding, Severity
from ..spec import Spec
from ..units import parse_value

__all__ = ["rule", "Rule", "RuleContext", "Finding", "Severity", "load_rules"]

PHASE_DESIGN = 1
PHASE_HARDEN = 3


@dataclass
class RuleContext:
    netlist: Netlist
    db: PartsDB
    spec: Spec
    phase: int = PHASE_DESIGN
    skidl_erc: list[tuple[str, str]] = field(default_factory=list)

    def pdef(self, c: Component) -> PartDef | None:
        return self.db.get(c.part_key)

    def components_of_kind(self, *kinds: str) -> list[Component]:
        out = []
        for c in self.netlist.components.values():
            pd = self.pdef(c)
            if pd and pd.kind in kinds:
                out.append(c)
        return sorted(out, key=lambda c: c.ref)

    def value(self, c: Component) -> float | None:
        try:
            return parse_value(c.value)
        except ValueError:
            return None

    def external_nets(self) -> set[str]:
        """Nets the simulation harness / outside world connects to."""
        return self.spec.required_nets()


@dataclass
class Rule:
    id: str
    description: str
    func: Callable[[RuleContext], list[Finding]]
    min_phase: int = PHASE_DESIGN
    origin: str = "builtin"

    def __call__(self, ctx: RuleContext) -> list[Finding]:
        return self.func(ctx)


_REGISTRY: dict[str, Rule] = {}
_current_origin = "builtin"


def rule(rule_id: str, description: str, min_phase: int = PHASE_DESIGN):
    def deco(fn: Callable[[RuleContext], list[Finding]]):
        _REGISTRY[rule_id] = Rule(rule_id, description, fn, min_phase, _current_origin)
        return fn

    return deco


_BUILTIN = (
    "builtin_parts",
    "builtin_connectivity",
    "builtin_decoupling",
    "builtin_led",
    "builtin_protection",
)


def load_rules(project_dir: Path | None = None) -> list[Rule]:
    global _current_origin
    _REGISTRY.clear()
    _current_origin = "builtin"
    for mod in _BUILTIN:
        importlib.reload(importlib.import_module(f"{__name__}.{mod}"))
    for ep in entry_points(group="circuitloop.rules"):
        _current_origin = f"plugin:{ep.name}"
        ep.load()
    if project_dir is not None and (project_dir / "rules").is_dir():
        for path in sorted((project_dir / "rules").glob("*.py")):
            _current_origin = f"project:{path.name}"
            spec = importlib.util.spec_from_file_location(f"cloop_project_rule_{path.stem}", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
    _current_origin = "builtin"
    return sorted(_REGISTRY.values(), key=lambda r: r.id)
