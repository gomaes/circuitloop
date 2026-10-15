from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed")


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
