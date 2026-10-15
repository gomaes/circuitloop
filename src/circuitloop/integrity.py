"""Tamper detection for files the design agent must not modify.

The orchestrator snapshots the SHA-256 of the spec, parts DB, rules, checklists,
the verifier source code itself and every read-only copy handed to an agent, and
re-checks after each agent step. Directories are tracked recursively, so added and
deleted files are detected too.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in _SKIP_DIRS for part in p.parts) and p.suffix != ".pyc":
            out.append(p)
    return out


@dataclass
class Integrity:
    roots: list[str] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)

    def add(self, *paths: Path) -> None:
        for root in paths:
            r = str(root.resolve())
            if r not in self.roots:
                self.roots.append(r)
            for f in _files(root.resolve()):
                self.hashes[str(f)] = sha256(f)

    def check(self) -> list[str]:
        """Return human-readable violations (empty list = intact)."""
        problems = []
        current: dict[str, str] = {}
        for r in self.roots:
            rp = Path(r)
            if not rp.exists():
                problems.append(f"removed: {r}")
                continue
            for f in _files(rp):
                current[str(f)] = sha256(f)
        for path, h in sorted(self.hashes.items()):
            if path not in current:
                problems.append(f"deleted: {path}")
            elif current[path] != h:
                problems.append(f"modified: {path}")
        for path in sorted(set(current) - set(self.hashes)):
            problems.append(f"added: {path}")
        return problems

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"roots": self.roots, "hashes": self.hashes}, indent=2))


def make_readonly(path: Path) -> None:
    for f in _files(path):
        f.chmod(0o444)
