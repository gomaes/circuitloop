"""Phase 5 outputs: netlist, schematic, perfboard layout, BOM, build guide, final report."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..gates import VerifyOutcome
from ..gates.g3_sim import summarize_waveforms
from ..layout.board import LayoutError, build_layout, verify_layout
from ..layout.render import SVG_STYLE, component_side_svg, net_color, solder_side_svg, standalone_svg
from ..partsdb import PartsDB
from ..results import Finding, GateResult, Severity, Status
from ..spec import Spec
from .bom import write_bom
from .guide import build_guide
from .plots import plot_waveforms
from .schematic import schematic_svg
from .shopping import shopping_items, write_shopping_list


@dataclass
class ExportResult:
    ok: bool
    files: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    layout_gate: GateResult | None = None


def _measured_nets(spec: Spec) -> tuple[list[str], dict]:
    nets, limits = [], {}
    for c in spec.acceptance:
        for attr in ("net", "input_net", "output_net"):
            n = getattr(c, attr, None)
            if n and n not in nets:
                nets.append(n)
        if getattr(c, "type", "") == "dc_voltage":
            limits[c.net] = (c.min, c.max)
    for ld in spec.loads:
        if ld.net not in nets:
            nets.append(ld.net)
    return nets, limits


def _derating_table(outcome: VerifyOutcome) -> list[str]:
    rows = outcome.sim.result.metrics.get("ratings", []) if outcome.sim else []
    worst: dict[tuple[str, str], dict] = {}
    for r in rows:
        lim = r["limit_hi"] if r["peak"] >= 0 or r["limit_lo"] is None else abs(r["limit_lo"])
        u = abs(r["peak"]) / lim if lim else 0
        key = (r["ref"], r["rating"])
        if key not in worst or u > worst[key]["u"]:
            worst[key] = {**r, "u": u}
    out = ["| part | rating | worst value | derated limit | utilisation |", "|---|---|---|---|---|"]
    for (ref, rating), r in sorted(worst.items(), key=lambda kv: -kv[1]["u"]):
        lim = (
            f"{r['limit_lo']:.3g}..{r['limit_hi']:.3g}"
            if r["limit_lo"] is not None
            else f"{r['limit_hi']:.3g}"
        )
        out.append(f"| {ref} ({r['part']}) | {rating} | {r['peak']:.4g} | {lim} | {r['u']:.0%} |")
    return out


def export_all(
    design: Path, outcome: VerifyOutcome, spec: Spec, db: PartsDB, out_dir: Path, run_dir: Path
) -> ExportResult:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    res = ExportResult(True)
    nl = outcome.netlist
    files = res.files
    shutil.copy(design, out_dir / "design.py")
    files.append(out_dir / "design.py")
    if outcome.netlist_path is not None:
        shutil.copy(outcome.netlist_path, out_dir / f"{spec.name}.net")
        files.append(out_dir / f"{spec.name}.net")
    if nl is None:
        res.ok = False
        res.findings.append(Finding("export.netlist", Severity.ERROR, "no netlist available"))
        return res

    # schematic + BOM
    (out_dir / "schematic.svg").write_text(schematic_svg(nl, db, spec.name, spec.ground_net))
    rows = write_bom(nl, db, out_dir / "bom.csv")
    files += [out_dir / "schematic.svg", out_dir / "bom.csv"]

    # layout (gate G6)
    try:
        lay = build_layout(nl, db, spec.board.max_cols, spec.board.max_rows)
        g6 = verify_layout(lay, nl, spec.board.max_cols, spec.board.max_rows)
    except (LayoutError, KeyError) as e:
        lay, g6 = (
            None,
            GateResult(
                "G6", "perfboard layout", Status.FAIL, [Finding("layout.error", Severity.ERROR, str(e))]
            ),
        )
    res.layout_gate = g6
    outcome.report.gates.append(g6)
    if lay is not None:
        top = component_side_svg(lay, nl, db, spec.name)
        bottom = solder_side_svg(lay, spec.ground_net, spec.name)
        (out_dir / "layout_component_side.svg").write_text(standalone_svg(top))
        (out_dir / "layout_solder_side.svg").write_text(standalone_svg(bottom))
        guide = build_guide(lay, nl, db, spec.name, spec.ground_net)
        (out_dir / "build_guide.md").write_text(guide)
        layout_json = {
            "cols": lay.cols,
            "rows": lay.rows,
            "parts": {
                r: {
                    "x": p.x,
                    "y": p.y,
                    "rot": p.rot,
                    "package": p.pkg.name,
                    "pads": {str(n): list(c) for n, c in p.pads().items()},
                }
                for r, p in lay.placed.items()
            },
            "traces": [{"net": t.net, "path": [list(c) for c in t.path]} for t in lay.traces],
            "jumpers": [{"net": j.net, "a": list(j.a), "b": list(j.b)} for j in lay.jumpers],
        }
        (out_dir / "layout.json").write_text(json.dumps(layout_json, indent=1))
        files += list(write_shopping_list(shopping_items(nl, db, layout_json), out_dir, spec.name))
        (out_dir / "layout.html").write_text(_html_page(spec, top, bottom, rows, guide, lay, nl))
        files += [
            out_dir / n
            for n in (
                "layout_component_side.svg",
                "layout_solder_side.svg",
                "build_guide.md",
                "layout.json",
                "layout.html",
            )
        ]
    if g6.status != Status.PASS:
        res.ok = False
        res.findings += g6.errors()

    # waveforms + final report
    pngs: list[Path] = []
    nets, limits = _measured_nets(spec)
    if outcome.sim is not None and spec.transient is not None:
        traces = summarize_waveforms(outcome.sim, nets)
        pngs = plot_waveforms(traces, nets, spec.transient.settle, limits, out_dir)
        files += pngs
    report_md = outcome.report.to_markdown()
    extra = ["", "## Component stress (worst case over all supply corners)", ""] + _derating_table(outcome)
    if lay is not None:
        m = g6.metrics
        extra += [
            "",
            "## Board",
            "",
            f"- size: {m['board_holes'][0]} × {m['board_holes'][1]} holes ({m['board_mm'][0]} × "
            f"{m['board_mm'][1]} mm)",
            f"- solder-side runs: {m['traces']}, jumpers: {m['jumpers']}",
        ]
    if pngs:
        extra += ["", "## Waveforms", ""] + [f"![{p.stem}]({p.name})" for p in pngs]
    if spec.assumptions:
        extra += ["", "## Assumptions in the specification (not stated in the request)", ""]
        extra += [f"- {a}" for a in spec.assumptions]
    extra += ["", "## Items not verified by simulation", ""]
    extra += [f"- {u}" for u in outcome.report.unverified] or ["- none"]
    extra += [
        "- physical layout parasitics, thermal coupling and EMC are not simulated",
        "- behavioural SPICE models are approximations of typical datasheet behaviour",
    ]
    (out_dir / "final_report.md").write_text(report_md + "\n".join(extra) + "\n")
    (out_dir / "final_report.json").write_text(json.dumps(outcome.report.to_dict(), indent=2, default=str))
    files += [out_dir / "final_report.md", out_dir / "final_report.json"]
    return res


def _html_page(spec: Spec, top: str, bottom: str, bom: list[dict], guide_md: str, lay, nl) -> str:
    e = html.escape
    legend = "".join(
        f'<li><span class="sw" style="background:{net_color(n, spec.ground_net)}"></span>{e(n)}</li>'
        for n in sorted(lay.nets)
    )
    bom_rows = "".join(
        f"<tr><td>{e(r['refs'])}</td><td>{r['qty']}</td><td>{e(r['part'])}</td><td>{e(str(r['value']))}</td>"
        f"<td>{e(r['mpn'])}</td><td>{e(r['description'])}</td></tr>"
        for r in bom
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(spec.name)} perfboard</title>
<style>
:root{{--bg:#faf9f6;--fg:#1f1f1e;--muted:#6b6a63;--line:#e4e3dd;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1a1a19;--fg:#f0efec;--muted:#c3c2b7;--line:#3a3a37;--card:#232321}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1200px;margin:0 auto;padding:16px}}
h1{{font-size:22px;margin:8px 0}} h2{{font-size:17px;margin-top:28px}}
.muted{{color:var(--muted)}} .sides{{display:flex;flex-wrap:wrap;gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto}}
ul.legend{{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:6px 16px}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left}}
pre{{white-space:pre-wrap;font-size:13px}}
{SVG_STYLE}
</style></head><body><main>
<h1>{e(spec.name)} — perfboard layout</h1>
<p class="muted">{e(spec.description.strip())}</p>
<p>{lay.cols} × {lay.rows} holes ({lay.cols * 2.54:.1f} × {lay.rows * 2.54:.1f} mm), {len(lay.traces)} solder-side runs,
{len(lay.jumpers)} jumper wire(s). Hover parts, pads and wires for details.</p>
<div class="sides"><div class="card">{top}</div><div class="card">{bottom}</div></div>
<h2>Nets</h2><ul class="legend">{legend}</ul>
<h2>Bill of materials</h2><div class="card"><table><thead><tr><th>refs</th><th>qty</th><th>part</th><th>value</th>
<th>MPN</th><th>description</th></tr></thead><tbody>{bom_rows}</tbody></table></div>
<h2>Build guide</h2><div class="card"><pre>{e(guide_md)}</pre></div>
</main></body></html>
"""
