"""spec.yaml schema (pydantic) and loader.

The spec is the single source of truth for what a design must achieve. It is
read-only for agents and hashed by the orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class SpecError(Exception):
    """Raised when spec.yaml cannot be read or fails validation."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PowerInput(_Model):
    type: Literal["dc"] = "dc"
    pos_net: str = Field("VIN", description="Net where the + side of the supply enters the board")
    neg_net: str = Field("GND", description="Net where the - side of the supply enters the board")
    v_min: float
    v_nom: float
    v_max: float
    source_resistance: float = Field(0.05, gt=0, description="Internal resistance of the supply [ohm]")

    @model_validator(mode="after")
    def _order(self) -> PowerInput:
        if not (self.v_min <= self.v_nom <= self.v_max):
            raise ValueError("power_input requires v_min <= v_nom <= v_max")
        return self

    def corners(self) -> dict[str, float]:
        out = {"vmin": self.v_min, "vnom": self.v_nom, "vmax": self.v_max}
        # Collapse duplicates so a fixed supply only simulates once.
        seen: dict[float, str] = {}
        for k, v in out.items():
            seen.setdefault(v, k)
        return {k: v for v, k in seen.items()}


class Load(_Model):
    net: str
    ref_net: str | None = None
    current: float | None = Field(None, gt=0, description="Constant-current load [A]")
    resistance: float | None = Field(None, gt=0, description="Resistive load [ohm]")

    @model_validator(mode="after")
    def _one(self) -> Load:
        if (self.current is None) == (self.resistance is None):
            raise ValueError("load needs exactly one of 'current' or 'resistance'")
        return self


class Stimulus(_Model):
    net: str
    ref_net: str | None = None
    kind: Literal["dc", "sine", "pulse"]
    dc: float = 0.0
    amplitude: float = 0.0
    frequency: float = Field(1e3, gt=0)
    source_resistance: float = Field(50.0, ge=0)


class Transient(_Model):
    stop: float = Field(gt=0, description="Simulation end time [s]")
    step: float = Field(gt=0, description="Max time step [s]")
    settle: float = Field(0.0, ge=0, description="Measurements ignore t < settle [s]")
    save_step: float | None = Field(
        None,
        gt=0,
        description="Output sample interval [s] (default: step). Use for long switching simulations",
    )
    save_window_only: bool = Field(
        False, description="Only store t >= settle (keeps raw files small for switching converters)"
    )

    @model_validator(mode="after")
    def _window(self) -> Transient:
        if self.settle >= self.stop:
            raise ValueError("transient.settle must be < transient.stop")
        return self


class _Criterion(_Model):
    id: str | None = None

    def key(self) -> str:
        return self.id or self.default_id()

    def default_id(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class DcVoltage(_Criterion):
    type: Literal["dc_voltage"]
    net: str
    min: float
    max: float

    def default_id(self) -> str:
        return f"dc_voltage_{self.net}"


class Ripple(_Criterion):
    type: Literal["ripple"]
    net: str
    max: float = Field(gt=0, description="Max peak-to-peak voltage over the measurement window [V]")

    def default_id(self) -> str:
        return f"ripple_{self.net}"


class Frequency(_Criterion):
    type: Literal["frequency"]
    net: str
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    def default_id(self) -> str:
        return f"frequency_{self.net}"


class Gain(_Criterion):
    type: Literal["gain"]
    input_net: str
    output_net: str
    min: float
    max: float

    def default_id(self) -> str:
        return f"gain_{self.output_net}"


class InputPower(_Criterion):
    type: Literal["input_power"]
    max: float = Field(gt=0, description="Max power drawn from the input supply [W]")

    def default_id(self) -> str:
        return "input_power"


class InputCurrent(_Criterion):
    type: Literal["input_current"]
    max: float = Field(gt=0, description="Max average current drawn from the input supply [A]")

    def default_id(self) -> str:
        return "input_current"


Criterion = Annotated[
    DcVoltage | Ripple | Frequency | Gain | InputPower | InputCurrent, Field(discriminator="type")
]

TRANSIENT_CRITERIA = (Ripple, Frequency, Gain)


class Derating(_Model):
    voltage: float = Field(0.8, gt=0, le=1)
    current: float = Field(0.8, gt=0, le=1)
    power: float = Field(0.5, gt=0, le=1)


class Board(_Model):
    type: Literal["perfboard"] = "perfboard"
    max_cols: int = Field(30, ge=5, le=200)
    max_rows: int = Field(20, ge=5, le=200)


class PartsPolicy(_Model):
    tht_only: bool = True
    forbidden: list[str] = Field(default_factory=list)


Protection = Literal["reverse_polarity", "overcurrent", "overvoltage", "esd", "input_protection"]


class NetLimit(_Model):
    min: float | None = None
    max: float | None = None


class FaultExpect(_Model):
    nets: dict[str, NetLimit] = Field(default_factory=dict)
    max_input_current: float | None = Field(None, gt=0, description="|I| drawn from the source [A]")
    abs_max_ratings: bool = Field(True, description="No part may exceed its absolute maximum ratings")


class Fault(_Model):
    name: str
    kind: Literal["reverse_polarity", "overvoltage"]
    voltage: float | None = Field(None, description="Applied input voltage (overvoltage)")
    expect: FaultExpect = Field(default_factory=FaultExpect)

    @model_validator(mode="after")
    def _v(self) -> Fault:
        if self.kind == "overvoltage" and self.voltage is None:
            raise ValueError(f"fault '{self.name}': overvoltage requires 'voltage'")
        return self


class ToleranceAnalysis(_Model):
    enabled: bool = Field(
        True, description="Run G7 in the final verification (Phase 4 / verify --phase final)"
    )
    method: Literal["worst_case", "monte_carlo"] = "worst_case"
    samples: int = Field(30, ge=1, le=1000, description="monte_carlo: number of samples")
    seed: int = 1


class Regression(_Model):
    max_drift: float | None = Field(
        None, gt=0, description="Max relative change of a criterion value vs. the Phase 1 baseline"
    )


class Spec(_Model):
    name: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    description: str
    ground_net: str = "GND"
    power_input: PowerInput
    loads: list[Load] = Field(default_factory=list)
    stimuli: list[Stimulus] = Field(default_factory=list)
    transient: Transient | None = None
    acceptance: list[Criterion] = Field(min_length=1)
    derating: Derating = Field(default_factory=Derating)
    board: Board = Field(default_factory=Board)
    parts_policy: PartsPolicy = Field(default_factory=PartsPolicy)
    protection: list[Protection] = Field(default_factory=list)
    faults: list[Fault] = Field(default_factory=list)
    regression: Regression = Field(default_factory=Regression)
    tolerance: ToleranceAnalysis = Field(default_factory=ToleranceAnalysis)
    allow_incomplete_sim: bool = False

    @model_validator(mode="after")
    def _consistency(self) -> Spec:
        keys = [c.key() for c in self.acceptance]
        dup = {k for k in keys if keys.count(k) > 1}
        if dup:
            raise ValueError(f"duplicate acceptance ids: {sorted(dup)} (set explicit 'id')")
        if any(isinstance(c, TRANSIENT_CRITERIA) for c in self.acceptance) and self.transient is None:
            raise ValueError("ripple/frequency/gain criteria require a 'transient' section")
        if self.power_input.neg_net != self.ground_net:
            raise ValueError("power_input.neg_net must equal ground_net")
        names = [f.name for f in self.faults]
        if len(set(names)) != len(names):
            raise ValueError("fault names must be unique")
        return self

    # -- helpers -----------------------------------------------------------
    def required_nets(self) -> set[str]:
        """Nets the design must contain so the harness can attach to them."""
        nets = {self.power_input.pos_net, self.ground_net}
        nets |= {ld.net for ld in self.loads}
        nets |= {s.net for s in self.stimuli}
        for c in self.acceptance:
            for attr in ("net", "input_net", "output_net"):
                if hasattr(c, attr):
                    nets.add(getattr(c, attr))
        for f in self.faults:
            nets |= set(f.expect.nets)
        return nets

    def effective_faults(self) -> list[Fault]:
        """Faults from the spec plus defaults implied by protection requirements."""
        faults = list(self.faults)
        kinds = {f.kind for f in faults}
        if "reverse_polarity" in self.protection and "reverse_polarity" not in kinds:
            faults.append(Fault(name="auto_reverse_polarity", kind="reverse_polarity"))
        return faults


def load_spec(path: str | Path) -> Spec:
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SpecError(f"spec file not found: {p}") from e
    except yaml.YAMLError as e:
        raise SpecError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise SpecError(f"{p}: top level must be a mapping")
    try:
        return Spec.model_validate(raw)
    except ValidationError as e:
        raise SpecError(f"{p}: schema validation failed\n{e}") from e
