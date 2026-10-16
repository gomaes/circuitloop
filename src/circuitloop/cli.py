"""`cloop` command-line interface."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import EXIT_ENV_ERROR, EXIT_OK, __version__
from .resources import data_dir, template_path

app = typer.Typer(
    name="cloop",
    help="circuitloop: AI-driven perfboard circuit design with deterministic verification gates.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err = Console(stderr=True)

AgentOpt = Annotated[
    str | None, typer.Option("--agent", help="Agent backend: claude | opencode", show_default=False)
]
MaxIterOpt = Annotated[int | None, typer.Option("--max-iter", min=1, help="Fix attempts per phase")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output")]
JobsOpt = Annotated[
    int | None, typer.Option("--jobs", "-j", min=1, help="Parallel ngspice processes (default: automatic)")
]


def _version_cb(value: bool) -> None:
    if value:
        console.print(f"circuitloop {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_cb, is_eager=True, help="Show version")
    ] = False,
) -> None:
    pass


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Project directory to create")],
    example: Annotated[
        str | None, typer.Option("--example", help="Start from a bundled example (see examples/)")
    ] = None,
) -> None:
    """Create a project directory with spec.yaml and cloop.toml from templates."""
    dest = Path(name)
    if dest.exists() and any(dest.iterdir()):
        err.print(f"[red]error:[/] {dest} already exists and is not empty")
        raise typer.Exit(EXIT_ENV_ERROR)
    dest.mkdir(parents=True, exist_ok=True)
    if example:
        src = data_dir("examples") / example / "spec.yaml"
        if not src.is_file():
            avail = sorted(p.name for p in data_dir("examples").iterdir() if (p / "spec.yaml").is_file())
            err.print(f"[red]error:[/] unknown example '{example}'. available: {', '.join(avail)}")
            shutil.rmtree(dest)
            raise typer.Exit(EXIT_ENV_ERROR)
        shutil.copy(src, dest / "spec.yaml")
    else:
        text = template_path("spec.yaml").read_text().replace("my_circuit", _safe_name(dest.name))
        (dest / "spec.yaml").write_text(text)
    shutil.copy(template_path("cloop.toml"), dest / "cloop.toml")
    (dest / "parts").mkdir(exist_ok=True)
    (dest / "rules").mkdir(exist_ok=True)
    (dest / ".gitignore").write_text("runs/\n")
    console.print(f"created [bold]{dest}/[/] — edit spec.yaml, then run: [bold]cd {dest} && cloop run[/]")


def _safe_name(s: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_\-]", "_", s) or "circuit"


@app.command()
def doctor(agent: AgentOpt = None) -> None:
    """Check dependencies (Python, ngspice, agent CLIs) and print install hints."""
    from .config import load_config
    from .doctor import run_checks

    backend = agent or load_config(Path.cwd()).agent.backend
    checks = run_checks(backend)
    t = Table(title="cloop doctor")
    for col in ("check", "status", "detail", "how to fix"):
        t.add_column(col)
    failed = False
    for c in checks:
        if c.ok:
            status = "[green]ok[/]"
        elif c.required:
            status, failed = "[red]missing[/]", True
        else:
            status = "[yellow]optional[/]"
        t.add_row(c.name, status, c.detail, c.hint if not c.ok else "")
    console.print(t)
    if failed:
        err.print("[red]required dependencies are missing[/]")
        raise typer.Exit(EXIT_ENV_ERROR)
    console.print("[green]all required dependencies found[/]")


def _load_spec_or_exit(path: Path):
    from .spec import SpecError, load_spec

    try:
        return load_spec(path)
    except SpecError as e:
        err.print(f"[red]spec error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e


def _find_spec(explicit: Path | None, near: Path) -> Path:
    for cand in [explicit, near / "spec.yaml", Path.cwd() / "spec.yaml"]:
        if cand is not None and cand.is_file():
            return cand
    err.print("[red]error:[/] spec.yaml not found (use --spec)")
    raise typer.Exit(EXIT_ENV_ERROR)


@app.command()
def verify(
    design: Annotated[Path, typer.Argument(help="design.py to verify", exists=True, dir_okay=False)],
    spec: Annotated[Path | None, typer.Option("--spec", help="spec.yaml (default: next to design)")] = None,
    phase: Annotated[str, typer.Option(help="design (G1-G3) | final (+protection rules, faults)")] = "final",
    baseline: Annotated[
        Path | None, typer.Option(help="baseline.json from a run, enables the G4 regression gate")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Directory for reports (default: <design dir>/verify)")
    ] = None,
    quick: Annotated[
        bool,
        typer.Option(
            "--quick", help="Fast self-check: nominal supply only, no faults/regression (not authoritative)"
        ),
    ] = False,
    jobs: JobsOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Run the verification gates only (e.g. on a hand-edited design)."""
    import json

    from . import EXIT_DESIGN_FAILED
    from .config import load_config
    from .gates import VerifyContext
    from .gates import verify as run_verify
    from .partsdb import PartsDBError, load_db

    if phase not in ("design", "final"):
        err.print("[red]error:[/] --phase must be 'design' or 'final'")
        raise typer.Exit(EXIT_ENV_ERROR)
    spec_path = _find_spec(spec, design.resolve().parent)
    sp = _load_spec_or_exit(spec_path)
    project = spec_path.resolve().parent
    cfg = load_config(project)
    try:
        db = load_db(project)
    except PartsDBError as e:
        err.print(f"[red]parts DB error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    base = None
    if baseline is not None:
        base = json.loads(baseline.read_text())
    outdir = (out or design.resolve().parent / "verify").resolve()
    ctx = VerifyContext(
        sp,
        db,
        project,
        design_timeout=cfg.loop.design_timeout,
        sim_timeout=cfg.loop.sim_timeout,
        sim_jobs=jobs or cfg.loop.sim_jobs,
    )
    final = phase == "final"
    res = run_verify(
        design,
        outdir,
        ctx,
        phase=3 if final else 1,
        baseline=base,
        faults=final,
        phase_label=f"cloop verify ({phase}{', quick' if quick else ''})",
        quick=quick,
    )
    j, m = res.report.write(outdir)
    if verbose:
        console.print(res.report.to_markdown())
    _print_gate_table(res.report)
    console.print(f"report: {m}")
    raise typer.Exit(EXIT_OK if res.report.passed else EXIT_DESIGN_FAILED)


def _print_gate_table(report) -> None:
    t = Table(title=f"verification: {'PASSED' if report.passed else 'FAILED'}")
    for col in ("gate", "status", "errors"):
        t.add_column(col)
    colors = {"pass": "green", "fail": "red", "incomplete": "yellow", "skipped": "dim"}
    for g in report.gates:
        st = str(g.status)
        t.add_row(f"{g.gate} {g.title}", f"[{colors[st]}]{st}[/]", str(len(g.errors())))
    console.print(t)
    for g in report.gates:
        for f in g.errors()[:10]:
            console.print(f"  [red]{g.gate}[/] {f.rule}: {escape(f.message.splitlines()[0])}")


parts_app = typer.Typer(help="Manage the parts database.", no_args_is_help=True)
app.add_typer(parts_app, name="parts")


@parts_app.command("list")
def parts_list(
    kind: Annotated[str | None, typer.Option(help="Filter by kind (resistor, ic, ...)")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """List registered parts (bundled + user + project)."""
    import json

    from .partsdb import PartsDBError, load_db

    try:
        db = load_db(Path.cwd())
    except PartsDBError as e:
        err.print(f"[red]parts DB error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    parts = [db[k] for k in db.keys() if kind is None or db[k].kind == kind]
    if as_json:
        console.print_json(json.dumps([p.model_dump(exclude={"spice"}) for p in parts]))
        return
    t = Table(title=f"{len(parts)} parts")
    for col in ("key", "kind", "package", "pins", "spice", "description"):
        t.add_column(col)
    for p in parts:
        pins = " ".join(f"{n}:{d.name}" for n, d in sorted(p.pins.items()))
        t.add_row(p.key, p.kind, p.package, pins, p.spice.type if p.spice else "[red]none[/]", p.description)
    console.print(t)


@parts_app.command("add")
def parts_add(
    file: Annotated[Path, typer.Argument(help="YAML file with one or more part definitions", exists=True)],
    user: Annotated[bool, typer.Option("--user", help="Install into ~/.config/circuitloop/parts")] = False,
    force: Annotated[bool, typer.Option(help="Overwrite existing keys")] = False,
) -> None:
    """Validate part definitions and add them to the project (or user) parts DB."""
    import yaml

    from .config import user_config_dir
    from .partsdb import PartsDBError, load_db, load_file

    try:
        new = load_file(file)
    except PartsDBError as e:
        err.print(f"[red]invalid part definition:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    dest_dir = (user_config_dir() / "parts") if user else (Path.cwd() / "parts")
    existing = load_db(Path.cwd())
    clash = sorted(k for k in new if k in existing)
    if clash and not force:
        err.print(f"[red]error:[/] already registered: {', '.join(clash)} (use --force to override)")
        raise typer.Exit(EXIT_ENV_ERROR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "local.yaml"
    data = yaml.safe_load(dest.read_text()) if dest.is_file() else {}
    raw = yaml.safe_load(file.read_text())
    data.update(raw)
    dest.write_text(yaml.safe_dump(data, sort_keys=True, allow_unicode=True))
    for k, p in new.items():
        note = "" if p.spice else " [yellow](no SPICE model: designs using it will be INCOMPLETE)[/]"
        console.print(f"added [bold]{k}[/] -> {dest}{note}")


@app.command("shopping-list")
def shopping_list(
    project: Annotated[Path, typer.Argument(help="Project directory (uses its output/)")] = Path("."),
    boards: Annotated[int, typer.Option(min=1, help="Number of boards to build")] = 1,
    spares: Annotated[
        float, typer.Option(min=0, help="Extra fraction for small parts, e.g. 0.1 = +10 % (at least +1)")
    ] = 0.0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List everything to buy for the final design: components, IC sockets, perfboard and wire."""
    import json
    from dataclasses import asdict

    from .export.shopping import load_layout, shopping_items, write_shopping_list
    from .netlist import NetlistError, read_netlist
    from .partsdb import load_db

    out = project / "output"
    nets = sorted(out.glob("*.net"))
    if not nets:
        err.print(f"[red]error:[/] no netlist in {out} (run `cloop run` first)")
        raise typer.Exit(EXIT_ENV_ERROR)
    try:
        nl = read_netlist(nets[0])
    except NetlistError as e:
        err.print(f"[red]error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    items = shopping_items(nl, load_db(project.resolve()), load_layout(out / "layout.json"), boards, spares)
    if as_json:
        console.print_json(json.dumps([asdict(i) for i in items]))
        return
    t = Table(title=f"shopping list — {nets[0].stem} × {boards} board(s)")
    for col in ("item", "value", "qty", "part number", "refs / note"):
        t.add_column(col)
    for i in items:
        t.add_row(i.name, i.value, f"{i.qty:g} {i.unit}", i.mpn, i.note)
    console.print(t)
    csv_path, md_path = write_shopping_list(items, out, nets[0].stem, boards)
    console.print(f"written: {csv_path}, {md_path}")


def _resolve_agent(cfg, agent: str | None) -> None:
    if agent is not None:
        if agent not in ("claude", "opencode", "mock"):
            err.print(f"[red]error:[/] --agent must be claude or opencode, got {agent!r}")
            raise typer.Exit(EXIT_ENV_ERROR)
        cfg.agent.backend = agent


@app.command()
def run(
    spec: Annotated[Path, typer.Argument(help="spec.yaml (default: ./spec.yaml)")] = Path("spec.yaml"),
    from_phase: Annotated[
        str, typer.Option("--from", help="Resume the latest run from: design | harden | reverify | output")
    ] = "design",
    run_dir: Annotated[
        Path | None, typer.Option("--run", help="Run directory to resume (default: latest)")
    ] = None,
    agent: AgentOpt = None,
    max_iter: MaxIterOpt = None,
    jobs: JobsOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Run the full pipeline unattended: design -> verify -> harden -> re-verify -> output."""
    from .agents import AgentError, make_backend
    from .config import load_config
    from .orchestrator import Orchestrator

    if not spec.is_file():
        err.print(f"[red]error:[/] {spec} not found (create one with `cloop init`)")
        raise typer.Exit(EXIT_ENV_ERROR)
    cfg = load_config(spec.resolve().parent)
    _resolve_agent(cfg, agent)
    if max_iter is not None:
        cfg.loop.max_iter = max_iter
    if jobs is not None:
        cfg.loop.sim_jobs = jobs
    try:
        backend = make_backend(cfg.agent)
    except AgentError as e:
        err.print(f"[red]error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    code = Orchestrator(spec, cfg, backend, console=console, verbose=verbose).run(from_phase, run_dir)
    raise typer.Exit(code)


@app.command()
def status(
    project: Annotated[Path, typer.Argument(help="Project directory")] = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show progress and result of the latest run."""
    import json

    from .orchestrator import RunState, latest_run

    rd = latest_run(project.resolve())
    if rd is None:
        err.print("no runs found (start one with `cloop run`)")
        raise typer.Exit(EXIT_ENV_ERROR)
    st = RunState.load(rd)
    if as_json:
        console.print_json(json.dumps(st.__dict__, default=str))
        return
    colors = {"passed": "green", "failed": "red", "tampered": "red", "error": "yellow", "running": "cyan"}
    console.print(f"run: [bold]{rd}[/]")
    console.print(f"status: [{colors.get(st.status, 'white')}]{st.status}[/]  {st.message}")
    console.print(f"agent: {st.agent}   started: {st.started}   finished: {st.finished or '-'}")
    t = Table(title="phases")
    t.add_column("phase")
    t.add_column("status")
    t.add_column("iterations")
    for ph in ("design", "harden", "reverify", "output"):
        info = st.phases.get(ph, {})
        n = sum(1 for i in st.iterations if i["phase"] == ph)
        t.add_row(ph, info.get("status", "-"), str(n))
    console.print(t)
    for name in ("failure_report.md", "TAMPER_REPORT.md"):
        if (rd / name).is_file():
            console.print(f"see: {rd / name}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
