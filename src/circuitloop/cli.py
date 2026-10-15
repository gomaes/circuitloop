"""`cloop` command-line interface."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
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
    outdir = out or design.resolve().parent / "verify"
    ctx = VerifyContext(
        sp, db, project, design_timeout=cfg.loop.design_timeout, sim_timeout=cfg.loop.sim_timeout
    )
    final = phase == "final"
    res = run_verify(
        design,
        outdir,
        ctx,
        phase=3 if final else 1,
        baseline=base,
        faults=final,
        phase_label=f"cloop verify ({phase})",
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
            console.print(f"  [red]{g.gate}[/] {f.rule}: {f.message.splitlines()[0]}")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
