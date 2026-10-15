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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
