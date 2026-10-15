"""Phase 5 outputs."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..gates import VerifyOutcome
from ..partsdb import PartsDB
from ..results import Finding
from ..spec import Spec


@dataclass
class ExportResult:
    ok: bool
    files: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def export_all(
    design: Path, outcome: VerifyOutcome, spec: Spec, db: PartsDB, out_dir: Path, run_dir: Path
) -> ExportResult:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    files: list[Path] = []
    shutil.copy(design, out_dir / "design.py")
    files.append(out_dir / "design.py")
    if outcome.netlist_path is not None:
        shutil.copy(outcome.netlist_path, out_dir / f"{spec.name}.net")
        files.append(out_dir / f"{spec.name}.net")
    j, m = outcome.report.write(out_dir, "verification_report")
    files += [j, m]
    return ExportResult(True, files)
