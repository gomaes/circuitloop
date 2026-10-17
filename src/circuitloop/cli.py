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
    from . import budget

    agent_budget = budget.from_env()
    if agent_budget is not None:  # running inside a pipeline agent step
        ok, msg = budget.consume(agent_budget, f"{design} --phase {phase}")
        if not ok:
            err.print(f"[yellow]{msg}[/]")
            raise typer.Exit(EXIT_ENV_ERROR)
        if not quick:
            msg += "; --quick applied (agent self-checks are always quick)"
        quick = True
        console.print(f"[dim]{msg}[/]")
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


topo_app = typer.Typer(
    help="Topology library: deterministic design calculators that write a complete design.py.",
    no_args_is_help=True,
)
app.add_typer(topo_app, name="topology")


@topo_app.command("list")
def topology_list(
    spec: Annotated[Path | None, typer.Option("--spec", help="Show which topologies fit this spec")] = None,
) -> None:
    """List the available topologies (and whether they fit a spec)."""
    from .topologies import TOPOLOGIES

    sp = _load_spec_or_exit(spec) if spec else None
    t = Table(title=f"{len(TOPOLOGIES)} topologies")
    t.add_column("name")
    if sp:
        t.add_column("fits spec")
    t.add_column("summary")
    for name, top in TOPOLOGIES.items():
        row = [name]
        if sp:
            why = top.applicable(sp)
            row.append("[green]yes[/]" if why is None else f"[dim]no: {escape(why)}[/]")
        t.add_row(*row, top.summary)
    console.print(t)


@topo_app.command("show")
def topology_show(name: Annotated[str, typer.Argument(help="Topology name")]) -> None:
    """Explain a topology's design equations and parameters."""
    from .topologies import TOPOLOGIES

    top = TOPOLOGIES.get(name)
    if top is None:
        err.print(f"[red]error:[/] unknown topology '{name}' (available: {', '.join(TOPOLOGIES)})")
        raise typer.Exit(EXIT_ENV_ERROR)
    console.print(f"[bold]{name}[/] — {top.summary}\n\n{top.description}\n")
    t = Table(title="parameters (--set name=value)")
    for col in ("name", "default", "meaning"):
        t.add_column(col)
    for k, p in top.params.items():
        t.add_row(k, p.default, p.help)
    console.print(t)


def _agent_output_ok(path: Path) -> bool:
    """In an agent step, generated designs may only go to design.py in the agent's work directory."""
    import os

    work = os.environ.get("CLOOP_AGENT_WORKDIR")
    return work is None or path.resolve() == (Path(work) / "design.py").resolve()


@topo_app.command("generate")
def topology_generate(
    name: Annotated[str, typer.Argument(help="Topology name (see `cloop topology list`)")],
    spec: Annotated[Path, typer.Option("--spec", help="spec.yaml", exists=True, dir_okay=False)] = Path(
        "spec.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o", help="File to write")] = Path("design.py"),
    sets: Annotated[
        list[str] | None, typer.Option("--set", help="Override a parameter: name=value (repeatable)")
    ] = None,
    minimal: Annotated[
        bool, typer.Option("--minimal", help="Leave out the protection listed in spec.protection")
    ] = False,
) -> None:
    """Size every part for the spec and write a complete design.py (then run `cloop verify`)."""
    from .partsdb import PartsDBError, load_db
    from .topologies import TopologyError, generate

    sp = _load_spec_or_exit(spec)
    params = {}
    for item in sets or []:
        k, sep, v = item.partition("=")
        if not sep:
            err.print(f"[red]error:[/] --set expects name=value, got {item!r}")
            raise typer.Exit(EXIT_ENV_ERROR)
        params[k.strip()] = v.strip()
    if not _agent_output_ok(output):
        err.print("[red]error:[/] in a pipeline step the output must be design.py in the work directory")
        raise typer.Exit(EXIT_ENV_ERROR)
    try:
        db = load_db(spec.resolve().parent)
        gen = generate(name, sp, db, params, protect=not minimal)
    except (TopologyError, PartsDBError) as e:
        err.print(f"[red]cannot generate:[/] {escape(str(e))}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    output.write_text(gen.text)
    for n in gen.notes:
        console.print(f"  {escape(n)}")
    console.print(f"written: {output} — verify it with: cloop verify {output} --spec {spec}")


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


spec_app = typer.Typer(help="Check specifications.", no_args_is_help=True)
app.add_typer(spec_app, name="spec")


@spec_app.command("check")
def spec_check(file: Annotated[Path, typer.Argument(help="spec.yaml to check")] = Path("spec.yaml")) -> None:
    """Validate a spec (schema + sanity checks) and list the topologies that fit it."""
    from .specgen import check_file, summary
    from .topologies import applicable

    if not file.is_file():
        err.print(f"[red]error:[/] {file} not found")
        raise typer.Exit(EXIT_ENV_ERROR)
    sp, problems = check_file(file)
    if sp is not None:
        for line in summary(sp):
            console.print(f"  {escape(line)}")
        fits = [n for n, why in applicable(sp) if why is None]
        console.print(
            "fitting topologies: " + (", ".join(fits) or "none (the design is written by the agent)")
        )
    for p in problems:
        err.print(f"[red]problem:[/] {escape(p)}")
    if problems:
        raise typer.Exit(EXIT_ENV_ERROR)
    console.print("[green]spec OK[/]")


@app.command()
def new(
    request: Annotated[str, typer.Argument(help='What to build, e.g. "USB 5 V to 12 V boost converter"')],
    directory: Annotated[
        Path | None, typer.Option("--dir", help="Project directory (default: ./<spec name>)")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Start the design run without asking")] = False,
    no_run: Annotated[
        bool, typer.Option("--no-run", help="Only write the spec; run later with `cloop run`")
    ] = False,
    agent: AgentOpt = None,
    max_iter: MaxIterOpt = None,
    jobs: JobsOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Write spec.yaml from a short request with the agent, then run the whole pipeline."""
    from datetime import datetime

    from . import EXIT_DESIGN_FAILED
    from .agents import AgentError, make_backend
    from .config import load_config
    from .orchestrator import Orchestrator
    from .partsdb import PartsDBError, load_db
    from .specgen import generate_spec, summary

    cfg = load_config(Path.cwd())
    _resolve_agent(cfg, agent)
    try:
        backend = make_backend(cfg.agent)
        db = load_db(None)
    except (AgentError, PartsDBError) as e:
        err.print(f"[red]error:[/] {e}")
        raise typer.Exit(EXIT_ENV_ERROR) from e
    if not backend.available():
        err.print(f"[red]error:[/] agent CLI '{backend.executable}' not found (run `cloop doctor`)")
        raise typer.Exit(EXIT_ENV_ERROR)
    if directory is not None and directory.exists() and any(directory.iterdir()):
        err.print(f"[red]error:[/] {directory} already exists and is not empty")
        raise typer.Exit(EXIT_ENV_ERROR)
    staging = Path.cwd() / ".cloop_new" / datetime.now().strftime("%Y%m%d-%H%M%S")
    staging.mkdir(parents=True)
    console.print(f"[bold]circuitloop new[/]: writing the specification ({backend.name}) ...")
    res = generate_spec(
        request, staging, backend, db, cfg.agent.timeout, log=lambda m: console.print(escape(m))
    )
    if not res.ok:
        err.print(f"[red]could not produce a valid spec in {res.attempts} attempt(s):[/]")
        for p in res.problems:
            err.print(f"  - {escape(p)}")
        err.print(f"agent logs and the last draft: {staging}")
        raise typer.Exit(EXIT_DESIGN_FAILED)
    sp = res.spec
    dest = directory or Path.cwd() / sp.name
    n = 1
    while directory is None and dest.exists():
        n += 1
        dest = Path.cwd() / f"{sp.name}-{n}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(res.spec_path, dest / "spec.yaml")
    toml = template_path("cloop.toml").read_text()
    toml = toml.replace('backend = "claude"', f'backend = "{cfg.agent.backend}"')
    if cfg.agent.model:
        toml = toml.replace('# model = "..."', f'model = "{cfg.agent.model}"')
    (dest / "cloop.toml").write_text(toml)
    (dest / "parts").mkdir(exist_ok=True)
    (dest / "rules").mkdir(exist_ok=True)
    (dest / ".gitignore").write_text("runs/\nspec_gen/\n")
    (dest / "request.md").write_text(f"# Request\n\n{request.strip()}\n")
    shutil.move(str(staging), dest / "spec_gen")
    console.print(f"\nspecification written: [bold]{dest / 'spec.yaml'}[/]")
    for line in summary(sp):
        console.print(f"  {escape(line)}")
    if sp.assumptions:
        console.print("[yellow]assumptions (not stated in the request — check them):[/]")
        for a in sp.assumptions:
            console.print(f"  - {escape(a)}")
    if no_run:
        console.print(f"review/edit the spec, then: [bold]cd {dest} && cloop run[/]")
        raise typer.Exit(EXIT_OK)
    if not yes:
        import sys

        if not sys.stdin.isatty():
            console.print(f"not starting without confirmation (use --yes); later: cd {dest} && cloop run")
            raise typer.Exit(EXIT_OK)
        if not typer.confirm("Start the design run with this specification?", default=True):
            console.print(f"stopped; edit {dest / 'spec.yaml'} and run `cloop run` there")
            raise typer.Exit(EXIT_OK)
    pcfg = load_config(dest)
    _resolve_agent(pcfg, agent)
    if max_iter is not None:
        pcfg.loop.max_iter = max_iter
    if jobs is not None:
        pcfg.loop.sim_jobs = jobs
    code = Orchestrator(dest / "spec.yaml", pcfg, backend, console=console, verbose=verbose).run()
    raise typer.Exit(code)


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
