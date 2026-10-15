"""Parts database (YAML).

Search path, later entries override earlier ones with the same key:
  1. bundled ``parts/*.yaml``
  2. ``$XDG_CONFIG_HOME/circuitloop/parts/*.yaml``
  3. ``<project>/parts/*.yaml``
Unregistered parts are an ERC error: every rating used for derating comes from here.
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
    "connector",
]


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


class SpiceDef(_M):
    type: Literal["primitive", "subckt", "equivalent", "connector"]
    line: str | None = Field(None, description="Element template; {ref} {value} {<pin>} placeholders")
    models: str | None = Field(None, description=".model / .subckt text this part needs")
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


class PartDef(_M):
    key: str = ""
    description: str
    kind: Kind
    mount: Literal["tht", "smd"] = "tht"
    package: str
    footprint: str
    mpn: str
    value: Literal["required", "fixed"] = "fixed"
    pins: dict[int, PinDef]
    ratings: list[Rating] = Field(min_length=1)
    decoupling: list[Decoupling] = Field(default_factory=list)
    spice: SpiceDef | None = None
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
        if self.spice and self.spice.line:
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
        return self.mpn.replace("{value}", value or "")


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

    def keys(self) -> list[str]:
        return sorted(self.parts)


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
        if not re.fullmatch(r"[A-Za-z0-9_./\-]+", str(key)):
            raise PartsDBError(f"{path}: invalid part key {key!r}")
        try:
            pd = PartDef.model_validate(body)
        except ValidationError as e:
            raise PartsDBError(f"{path}: part {key}: {e}") from e
        pd.key, pd.source = str(key), str(path)
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
            parse_value(value)
        except ValueError as e:
            return str(e)
    return None
