"""Pipeline configuration (cloop.toml) — agent backend, loop limits, timeouts.

Resolution order (later wins): defaults < ~/.config/circuitloop/config.toml
< <project>/cloop.toml < CLI options.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["claude", "opencode", "mock"]


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: AgentName = "claude"
    model: str | None = None
    timeout: int = Field(900, gt=0, description="Seconds per agent call (the step is cut off after this)")
    max_self_checks: int = Field(
        4,
        ge=0,
        description="`cloop verify` self-checks an agent may run per step (always --quick); the pipeline "
        "verifies authoritatively afterwards anyway",
    )
    max_budget_usd: float | None = Field(None, gt=0, description="claude only: per-call budget cap")
    extra_args: list[str] = Field(default_factory=list)


class LoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_iter: int = Field(5, ge=1, le=50)
    design_timeout: int = Field(120, gt=0, description="Seconds allowed for running design.py")
    sim_timeout: int = Field(300, gt=0, description="Seconds allowed per ngspice run")
    sim_jobs: int | None = Field(
        None, ge=1, description="Parallel ngspice processes (default: automatic = min(CPUs, scenarios))"
    )
    review: bool = True
    keep_raw: bool = Field(
        False,
        description="Keep ngspice raw waveform files of every iteration (they reach GBs per run); the "
        "decks, logs, reports and output waveform plots are always kept",
    )


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: AgentConfig = Field(default_factory=AgentConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)


def user_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "circuitloop"


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(project_dir: Path | None = None) -> Config:
    data: dict = {}
    for p in (user_config_dir() / "config.toml", (project_dir / "cloop.toml") if project_dir else None):
        if p and p.is_file():
            with p.open("rb") as f:
                data = _merge(data, tomllib.load(f))
    return Config.model_validate(data)
