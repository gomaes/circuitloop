"""Parts database (YAML).

Search path, later entries override earlier ones with the same key:
  1. bundled ``parts/*.yaml``
  2. ``$XDG_CONFIG_HOME/circuitloop/parts/*.yaml``
  3. ``<project>/parts/*.yaml``
Unregistered parts are an ERC error: every rating used for derating comes from here.

A part with a value range can list ``sizes``: the body (package/footprint), datasheet figures and
ratings that change with the value, e.g. an electrolytic family whose can grows from 5 mm to 16 mm.
``db.resolve(key, value)`` returns the part as it applies to one value; everything that looks at a
placed component (ratings, layout, BOM, SPICE) goes through it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .config import user_config_dir
from .resources import data_dir
from .units import parse_value

PinType = Literal["passive", "input", "output", "power_in", "power_out", "bidirectional"]
Kind = Literal[
    "resistor",
    "capacitor",
    "electrolytic",
    "diode",
    "zener",
    "tvs",
    "led",
    "transistor",
    "mosfet",
    "regulator",
    "ic",
    "opamp",
    "ptc",
    "fuse",
    "inductor",
    "connector",
    "bridge",
    "comparator",
]

# reference-designator prefix per kind (R1, C3, U2, ...)
REF_PREFIX = {
    "resistor": "R",
    "capacitor": "C",
    "electrolytic": "C",
    "diode": "D",
    "zener": "D",
    "tvs": "D",
    "led": "D",
    "transistor": "Q",
    "mosfet": "Q",
    "regulator": "U",
    "ic": "U",
    "opamp": "U",
    "ptc": "F",
    "fuse": "F",
    "inductor": "L",
    "connector": "J",
    "bridge": "D",
    "comparator": "U",
}


class PartsDBError(Exception):
    pass


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PinDef(_M):
    name: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    type: PinType = "passive"
    optional: bool = Field(False, description="May be left unconnected")


class Rating(_M):
    type: Literal["voltage", "current", "power"]
    max: float = Field(gt=0)
    min: float | None = Field(None, description="voltage/current lower limit; default -max")
    pins: list[int] | None = Field(None, description="voltage: [a, b] -> V(a)-V(b)")
    pin: int | None = Field(None, description="current: current flowing into this pin")
    mode: Literal["peak", "average", "rms"] = Field(
        "peak",
        description="current: compare the peak (default), the average (e.g. diode If(AV)) or the RMS value "
        "(e.g. inductor/PTC rated current) over the steady-state window",
    )

    @model_validator(mode="after")
    def _shape(self) -> Rating:
        if self.type == "voltage" and (self.pins is None or len(self.pins) != 2):
            raise ValueError("voltage rating needs pins: [a, b]")
        if self.type == "current" and self.pin is None:
            raise ValueError("current rating needs pin")
        return self

    @property
    def lower(self) -> float:
        return -self.max if self.min is None else self.min


class SpiceParam(_M):
    value: float
    tolerance: float = Field(0.0, ge=0, lt=1, description="relative manufacturing tolerance (0.02 = +/-2 %)")


class SpiceDef(_M):
    type: Literal["primitive", "subckt", "equivalent", "connector"]
    line: str | None = Field(None, description="Element template; {ref} {value} {<pin>} placeholders")
    models: str | None = Field(None, description=".model / .subckt text this part needs")
    include: str | None = Field(
        None,
        description="External model file (e.g. a vendor .lib you downloaded), included with .include. "
        "Relative paths are relative to this YAML file; ~ is expanded. Not bundled with circuitloop.",
    )
    params: dict[str, SpiceParam] = Field(
        default_factory=dict, description="model parameters used as {p:name} in `line` (with tolerances)"
    )
    compat: Literal["ps", "lt", "ki"] | None = Field(
        None, description="ngspice compatibility mode the model needs (ps = PSpice, lt = LTspice, ki = KiCad)"
    )
    note: str | None = None

    @model_validator(mode="after")
    def _line(self) -> SpiceDef:
        if self.type != "connector" and not self.line:
            raise ValueError(f"spice type '{self.type}' needs 'line'")
        return self


class Decoupling(_M):
    pin: int
    gnd: int
    min: float = Field(gt=0, description="Minimum capacitance between pin and gnd [F]")


class Size(_M):
    """Value-dependent data of a part family; the first entry whose value_max covers the value applies."""

    value_max: float = Field(gt=0)
    package: str | None = None
    footprint: str | None = None
    mpn: str | None = None
    design: dict[str, float] = Field(default_factory=dict, description="overrides the part's design figures")
    ratings: list[Rating] | None = Field(
        None, description="replace the part's ratings of the same type (e.g. a ripple-current rating per can)"
    )


class PartDef(_M):
    key: str = ""
    description: str
    kind: Kind
    mount: Literal["tht", "smd"] = "tht"
    package: str
    footprint: str
    mpn: str
    value: Literal["required", "fixed"] = "fixed"
    value_min: float | None = Field(None, description="smallest allowed value (the package fits this range)")
    value_max: float | None = Field(None, description="largest allowed value (the package fits this range)")
    tolerance: float | None = Field(
        None,
        ge=0,
        lt=1,
        description="relative tolerance of the value (0.01 = +/-1 %), used by tolerance analysis",
    )
    pins: dict[int, PinDef]
    ratings: list[Rating] = Field(min_length=1)
    decoupling: list[Decoupling] = Field(default_factory=list)
    design: dict[str, float] = Field(
        default_factory=dict,
        description="typical datasheet figures used by design calculators and diagnosis "
        "(e.g. vf, esr, ciss, rds_on, dropout, vout, vref)",
    )
    spice: SpiceDef | None = None
    sizes: list[Size] = Field(
        default_factory=list,
        description="value-dependent package/footprint/design figures/ratings (ascending value_max)",
    )
    source: str = ""

    @model_validator(mode="after")
    def _pins(self) -> PartDef:
        nums = set(self.pins)
        names = [p.name for p in self.pins.values()]
        if len(set(names)) != len(names):
            raise ValueError("pin names must be unique")
        for r in self.ratings:
            for p in (r.pins or []) + ([r.pin] if r.pin is not None else []):
                if p not in nums:
                    raise ValueError(f"rating refers to unknown pin {p}")
        for d in self.decoupling:
            if d.pin not in nums or d.gnd not in nums:
                raise ValueError("decoupling refers to unknown pin")
        if self.sizes:
            limits = [z.value_max for z in self.sizes]
            if limits != sorted(limits):
                raise ValueError("sizes must be in ascending value_max order")
            if self.value != "required":
                raise ValueError("sizes need value: required")
            if self.value_max is None:
                self.value_max = limits[-1]
            elif self.value_max > limits[-1] * (1 + 1e-9):
                raise ValueError("value_max is above the largest size")
        if self.spice and self.spice.line:
            for name in re.findall(r"\{d:(\w+)\}", self.spice.line):
                if name not in self.design and not (self.sizes and all(name in z.design for z in self.sizes)):
                    raise ValueError(f"spice line uses design figure {{d:{name}}} that is not defined")
            for name in re.findall(r"\{p:(\w+)\}", self.spice.line):
                if name not in self.spice.params:
                    raise ValueError(f"spice line uses undefined parameter {{p:{name}}}")
            for ph in re.findall(r"\{(\d+)\}", self.spice.line):
                if int(ph) not in nums:
                    raise ValueError(f"spice line refers to unknown pin {ph}")
        return self

    def pin_by_name(self, name: str) -> int | None:
        for n, p in self.pins.items():
            if p.name == name:
                return n
        return None

    def mpn_for(self, value: str | None) -> str:
        return self.for_value(value).mpn.replace("{value}", value or "")

    def _size_ratings(self, size: Size) -> list[Rating]:
        if size.ratings is None:
            return self.ratings
        types = {r.type for r in size.ratings}
        return [r for r in self.ratings if r.type not in types] + list(size.ratings)

    def for_value(self, value: str | float | None) -> PartDef:
        """This part as it applies to one value (sizes resolved); itself when it has no sizes."""
        if not self.sizes or value is None:
            return self
        try:
            v = parse_value(value) if isinstance(value, str) else float(value)
        except ValueError:
            return self
        size = next((z for z in self.sizes if v <= z.value_max * (1 + 1e-9)), self.sizes[-1])
        return self.model_copy(
            update={
                "package": size.package or self.package,
                "footprint": size.footprint or self.footprint,
                "mpn": size.mpn or self.mpn,
                "design": {**self.design, **size.design},
                "ratings": self._size_ratings(size),
                "sizes": [],
            }
        )


class PartsDB:
    def __init__(self, parts: dict[str, PartDef], files: list[Path]):
        self.parts = parts
        self.files = files

    def __contains__(self, key: str) -> bool:
        return key in self.parts

    def __getitem__(self, key: str) -> PartDef:
        return self.parts[key]

    def get(self, key: str | None) -> PartDef | None:
        return self.parts.get(key) if key else None

    def resolve(self, key: str | None, value: str | None) -> PartDef | None:
        """The part as it applies to a placed component with this value (see PartDef.sizes)."""
        pd = self.get(key)
        return pd.for_value(value) if pd is not None else None

    def keys(self) -> list[str]:
        return sorted(self.parts)

    def model_files(self) -> list[Path]:
        """External SPICE model files referenced by parts (hashed like the DB itself)."""
        return sorted({Path(p.spice.include) for p in self.parts.values() if p.spice and p.spice.include})


def search_dirs(project_dir: Path | None = None) -> list[Path]:
    dirs = [data_dir("parts"), user_config_dir() / "parts"]
    if project_dir is not None:
        dirs.append(project_dir / "parts")
    env = os.environ.get("CLOOP_PARTS_PATH")
    if env:
        dirs = [Path(p) for p in env.split(os.pathsep) if p]
    return dirs


def load_file(path: Path) -> dict[str, PartDef]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise PartsDBError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise PartsDBError(f"{path}: top level must be a mapping of part keys")
    out: dict[str, PartDef] = {}
    for key, body in raw.items():
        if str(key).startswith("."):  # template holding YAML anchors (e.g. `.ecap_sizes: &d5 {...}`)
            continue
        if not re.fullmatch(r"[A-Za-z0-9_./\-]+", str(key)):
            raise PartsDBError(f"{path}: invalid part key {key!r}")
        try:
            pd = PartDef.model_validate(body)
        except ValidationError as e:
            raise PartsDBError(f"{path}: part {key}: {e}") from e
        pd.key, pd.source = str(key), str(path)
        if pd.spice and pd.spice.include:
            inc = Path(os.path.expanduser(pd.spice.include))
            pd.spice.include = str(inc if inc.is_absolute() else (path.parent / inc).resolve())
        out[str(key)] = pd
    return out


def db_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        if d.is_dir():
            files += sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
    return files


def load_db(project_dir: Path | None = None, dirs: list[Path] | None = None) -> PartsDB:
    files = db_files(dirs if dirs is not None else search_dirs(project_dir))
    parts: dict[str, PartDef] = {}
    for f in files:
        parts.update(load_file(f))
    return PartsDB(parts, files)


def check_value(pd: PartDef, value: str | None) -> str | None:
    """Return an error message if a value is missing/invalid for this part."""
    if pd.value == "required":
        if not value:
            return f"{pd.key} requires a value"
        try:
            v = parse_value(value)
        except ValueError as e:
            return str(e)
        if pd.value_min is not None and v < pd.value_min * (1 - 1e-9):
            return f"{pd.key}: value {value} is below the range of this part ({pd.value_min:g})"
        if pd.value_max is not None and v > pd.value_max * (1 + 1e-9):
            return (
                f"{pd.key}: value {value} is above the range of this part ({pd.value_max:g}); "
                "a larger value needs a bigger body/package — use another part"
            )
    return None
