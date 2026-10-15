"""Locate bundled data (parts DB, checklists, examples, prompts).

In a wheel the top-level ``parts/``, ``checklists/`` and ``examples/`` folders are
force-included under ``circuitloop/_data``; in a source checkout they live at the
repository root.
"""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent


def data_dir(name: str) -> Path:
    bundled = PKG_DIR / "_data" / name
    if bundled.is_dir():
        return bundled
    repo = PKG_DIR.parent.parent / name
    if repo.is_dir():
        return repo
    raise FileNotFoundError(f"bundled data directory '{name}' not found")


def prompt_path(name: str) -> Path:
    return PKG_DIR / "prompts" / name


def template_path(name: str) -> Path:
    return PKG_DIR / "templates" / name
