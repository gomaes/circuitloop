"""Apply a relaxation proposal (runs/<run>/relaxation.json) to spec.yaml and continue the run.

The orchestrator writes a proposal only when feasibility.py shows that an acceptance window is narrower
than the registered parts' tolerances allow. Each moved limit goes exactly to the verified worst-case
range of the design that passes everything else, rounded outward to 0.1 % of the window centre, so the
relaxation is the smallest one that design passes. spec.yaml keeps its comments (only the numbers are
replaced), the change is recorded under `assumptions`, and the previous file is kept in spec_history/.

Relaxing only widens limits, so the Phase 1-3 results of the previous run stay valid: the next run
continues at Phase 4 with the same design (Orchestrator.run(carry=...)).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.markup import escape

from . import EXIT_SPEC_INFEASIBLE
from .integrity import sha256
from .spec import Spec


class RelaxError(Exception):
    pass


def load_proposal(run_dir: Path) -> dict | None:
    p = run_dir / "relaxation.json"
    return json.loads(p.read_text()) if p.is_file() else None


def describe(changes: list[dict], spec: Spec) -> list[str]:
    """One line per criterion: 'frequency_VOUT 900..1100 -> 887..1112'."""
    out = []
    crit = {c.key(): c for c in spec.acceptance}
    for cid in dict.fromkeys(ch["criterion"] for ch in changes):
        c = crit[cid]
        new = {ch["field"]: ch["new"] for ch in changes if ch["criterion"] == cid}
        lo, hi = getattr(c, "min", None), getattr(c, "max", None)
        out.append(f"{cid} {_g(lo)}..{_g(hi)} -> {_g(new.get('min', lo))}..{_g(new.get('max', hi))}")
    return out


def _g(x) -> str:
    return "" if x is None else f"{x:.6g}"


def _mapping_get(node: yaml.MappingNode, key: str):
    for k, v in node.value:
        if getattr(k, "value", None) == key:
            return v
    return None


def edit_text(text: str, changes: list[dict], note: str) -> str:
    """Replace the limits in place and append `note` to `assumptions`; falls back to a full re-dump
    (comments lost) when the layout cannot be edited in place."""
    spec = Spec.model_validate(yaml.safe_load(text))
    index = {c.key(): i for i, c in enumerate(spec.acceptance)}
    try:
        out = _edit_in_place(text, changes, note, index)
        _check(out, changes, note, index)
        return out
    except (RelaxError, yaml.YAMLError, ValueError, AttributeError, IndexError):
        data = yaml.safe_load(text)
        for ch in changes:
            data["acceptance"][index[ch["criterion"]]][ch["field"]] = ch["new"]
        data.setdefault("assumptions", []).append(note)
        out = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
        _check(out, changes, note, index)
        return out


def _edit_in_place(text: str, changes: list[dict], note: str, index: dict[str, int]) -> str:
    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        raise RelaxError("top level is not a mapping")
    acc = _mapping_get(root, "acceptance")
    if not isinstance(acc, yaml.SequenceNode):
        raise RelaxError("acceptance is not a list")
    spans: list[tuple[int, int, str]] = []
    for ch in changes:
        item = acc.value[index[ch["criterion"]]]
        v = _mapping_get(item, ch["field"]) if isinstance(item, yaml.MappingNode) else None
        if not isinstance(v, yaml.ScalarNode):
            raise RelaxError(f"{ch['criterion']}.{ch['field']} not found")
        spans.append((v.start_mark.index, v.end_mark.index, f"{ch['new']:.6g}"))
    quoted = json.dumps(note, ensure_ascii=False)
    asm = _mapping_get(root, "assumptions")
    if asm is None:
        tail = ("" if text.endswith("\n") else "\n") + f"\nassumptions:\n  - {quoted}\n"
        spans.append((len(text), len(text), tail))
    elif isinstance(asm, yaml.SequenceNode) and not asm.flow_style and asm.value:
        last = asm.value[-1]
        eol = text.find("\n", last.end_mark.index)
        eol = len(text) if eol < 0 else eol
        col = asm.value[0].start_mark.column - 2
        if col < 0 or text[asm.value[0].start_mark.index - 2] != "-":
            raise RelaxError("unexpected assumptions layout")
        spans.append((eol, eol, "\n" + " " * col + f"- {quoted}"))
    else:
        raise RelaxError("assumptions is not a block list")
    for start, end, new in sorted(spans, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _check(text: str, changes: list[dict], note: str, index: dict[str, int]) -> None:
    spec = Spec.model_validate(yaml.safe_load(text))
    for ch in changes:
        got = getattr(spec.acceptance[index[ch["criterion"]]], ch["field"])
        if abs(got - ch["new"]) > 1e-9 * max(abs(ch["new"]), 1.0):
            raise RelaxError(f"{ch['criterion']}.{ch['field']} is {got}, expected {ch['new']}")
    if note not in spec.assumptions:
        raise RelaxError("assumption not recorded")


def apply(spec_path: Path, proposal: dict) -> list[str]:
    """Write the relaxed spec; returns the human-readable changes."""
    if proposal.get("spec_sha256") and sha256(spec_path) != proposal["spec_sha256"]:
        raise RelaxError(f"{spec_path} changed after the run that proposed the relaxation; run again")
    changes = proposal["changes"]
    if not changes:
        raise RelaxError("the proposal contains no changes")
    text = spec_path.read_text(encoding="utf-8")
    spec = Spec.model_validate(yaml.safe_load(text))
    lines = describe(changes, spec)
    note = (
        "Relaxed automatically: "
        + "; ".join(lines)
        + " — the original window was narrower than the worst-case spread of the registered parts' "
        "tolerances; this is the smallest range the verified design passes."
    )
    hist = spec_path.parent / "spec_history"
    hist.mkdir(exist_ok=True)
    shutil.copy(spec_path, hist / f"spec_{datetime.now().strftime('%Y%m%d-%H%M%S')}.yaml")
    spec_path.write_text(edit_text(text, changes, note), encoding="utf-8")
    return lines


def run_with_relaxation(
    spec_path: Path,
    cfg,
    backend,
    console: Console,
    verbose: bool = False,
    resume: bool = False,
) -> int:
    """Run the pipeline; when it stops with EXIT_SPEC_INFEASIBLE, relax minimally and continue.

    resume: first apply the proposal of the latest run if it ended infeasible (no new design run).
    Stops honestly (exit 4) when a relaxation would move a limit by more than loop.max_relax of the
    window centre or loop.relax_rounds is used up.
    """
    from .orchestrator import Orchestrator, RunState, latest_run

    project = spec_path.resolve().parent
    carry = None
    pending = None
    if resume:
        rd = latest_run(project)
        if rd is not None and RunState.load(rd).status == "infeasible":
            pending = rd
    for rnd in range(cfg.loop.relax_rounds + 1):
        if pending is None:
            code = Orchestrator(spec_path, cfg, backend, console=console, verbose=verbose).run(carry=carry)
            if code != EXIT_SPEC_INFEASIBLE:
                return code
            pending = latest_run(project)
        proposal = load_proposal(pending) if pending else None
        if proposal is None:
            console.print("[red]no relaxation proposal found[/]")
            return EXIT_SPEC_INFEASIBLE
        if rnd == cfg.loop.relax_rounds:
            console.print(f"[yellow]stopping: {cfg.loop.relax_rounds} relaxation round(s) used[/]")
            return EXIT_SPEC_INFEASIBLE
        change = proposal.get("max_relative_change", 0.0)
        if change > cfg.loop.max_relax:
            console.print(
                f"[yellow]not relaxing automatically:[/] the smallest relaxation moves a limit by "
                f"{change:.1%} of the window centre, more than loop.max_relax = {cfg.loop.max_relax:.0%}. "
                f"Decide yourself: see {pending / 'spec_infeasible.md'}"
            )
            return EXIT_SPEC_INFEASIBLE
        try:
            lines = apply(spec_path, proposal)
        except RelaxError as e:
            console.print(f"[red]cannot relax the spec:[/] {escape(str(e))}")
            return EXIT_SPEC_INFEASIBLE
        console.print(
            "\n[yellow bold]spec relaxed[/] (the original window cannot be met with the registered parts):"
        )
        for line in lines:
            console.print(f"  {escape(line)}")
        console.print(f"  recorded in {spec_path} (assumptions); previous version in spec_history/")
        carry = (pending, Path(proposal["design"]))
        pending = None
    return EXIT_SPEC_INFEASIBLE
