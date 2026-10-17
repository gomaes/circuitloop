"""Turn a short natural-language request into a validated spec.yaml (`cloop new`).

An agent writes the spec; the schema and the sanity checks below are deterministic and decide
whether it is accepted (fix loop with the errors fed back). Values the request does not state are
filled with conventional engineering defaults and listed in `assumptions:`, so the person can see
and change them before the design run starts. Once the run starts, the spec is protected exactly
like a hand-written one: the agents that design the circuit can never change it.
"""

from __future__ import annotations

import json
import shutil
import string
from dataclasses import dataclass, field
from pathlib import Path

from .agents import AgentBackend, AgentTask
from .budget import Budget
from .catalog import render_catalog
from .integrity import make_readonly
from .partsdb import PartsDB
from .resources import data_dir, prompt_path, template_path
from .spec import DcVoltage, Frequency, Gain, Ripple, Spec, SpecError, load_spec

MAX_ATTEMPTS = 3


def sanity(spec: Spec) -> list[str]:
    """Problems that pass the schema but make the spec unusable or the simulation meaningless."""
    out = []
    pin = spec.power_input
    func = [c for c in spec.acceptance if isinstance(c, DcVoltage | Ripple | Frequency | Gain)]
    if not func:
        out.append("acceptance has no functional criterion (dc_voltage, ripple, frequency or gain)")
    for c in spec.acceptance:
        if isinstance(c, DcVoltage) and c.net != pin.pos_net:
            if not any(ld.net == c.net for ld in spec.loads) and not any(
                s.net == c.net for s in spec.stimuli
            ):
                out.append(
                    f"output net {c.net} has no load in `loads`: state the output current "
                    "(or the assumed one, recorded in `assumptions`)"
                )
            if c.min >= c.max:
                out.append(f"{c.key()}: min must be below max")
            if c.min > pin.v_max and spec.transient is None:
                out.append(
                    f"{c.net} is above the input voltage (a switching converter): add a `transient` section"
                )
            if c.min > pin.v_max and spec.transient is not None and spec.transient.step > 1e-6:
                out.append(
                    "a step-up converter switches at ~50-100 kHz: transient.step must be <= 1e-6 "
                    "(see examples/usb_boost_12v: step 0.2e-6, settle >= 20 ms, save_window_only)"
                )
    if spec.transient is not None:
        tr = spec.transient
        window = tr.stop - tr.settle
        for c in spec.acceptance:
            if isinstance(c, Frequency) and window * c.min < 3:
                out.append(
                    f"{c.key()}: the measurement window (stop - settle = {window:g} s) holds fewer than "
                    f"3 periods at {c.min:g} Hz"
                )
            if isinstance(c, Gain):
                stim = next((s for s in spec.stimuli if s.net == c.input_net), None)
                if stim is None:
                    out.append(f"{c.key()}: no stimulus drives the input net {c.input_net}")
                elif window * stim.frequency < 3:
                    out.append(f"{c.key()}: the measurement window holds fewer than 3 stimulus periods")
    return out


def check_file(path: Path) -> tuple[Spec | None, list[str]]:
    """(spec, problems) — the spec is None when it does not even load."""
    try:
        spec = load_spec(path)
    except SpecError as e:
        return None, [str(e)]
    return spec, sanity(spec)


@dataclass
class SpecGenResult:
    ok: bool
    spec_path: Path | None = None
    spec: Spec | None = None
    attempts: int = 0
    problems: list[str] = field(default_factory=list)


def _topologies_text() -> str:
    from .topologies import TOPOLOGIES

    return "\n".join(f"- `{n}` — {t.summary}" for n, t in TOPOLOGIES.items())


def generate_spec(
    request: str,
    workdir: Path,
    backend: AgentBackend,
    db: PartsDB,
    timeout: int,
    log=print,
    max_attempts: int = MAX_ATTEMPTS,
) -> SpecGenResult:
    """Let the agent write spec.yaml in `workdir`; accept it only when schema and sanity checks pass."""
    ref = workdir / "ref"
    ref.mkdir(parents=True, exist_ok=True)
    shutil.copy(template_path("spec.yaml"), ref / "spec_template.yaml")
    (ref / "spec_schema.json").write_text(json.dumps(Spec.model_json_schema(), indent=1))
    ex = ref / "examples"
    ex.mkdir(exist_ok=True)
    for d in sorted(data_dir("examples").iterdir()):
        if (d / "spec.yaml").is_file():
            shutil.copy(d / "spec.yaml", ex / f"{d.name}.yaml")
    (ref / "parts_catalog.md").write_text(render_catalog(db))
    make_readonly(ref)
    problems: list[str] = []
    res = SpecGenResult(False)
    for attempt in range(1, max_attempts + 1):
        res.attempts = attempt
        feedback = ""
        if problems:
            feedback = (
                "\n## Your previous spec.yaml was rejected\n\nFix every problem below (keep everything else):\n\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\n"
            )
        instr = string.Template(prompt_path("specwriter.md").read_text()).safe_substitute(
            request=request.strip(), topologies=_topologies_text(), feedback=feedback
        )
        log_dir = workdir / "agent" / f"attempt_{attempt:02d}"
        b = Budget(0, log_dir / "self_checks.json", None)
        task = AgentTask("specwriter", instr, workdir, ["spec.yaml"], log_dir, timeout, env=b.env(workdir))
        log(f"  spec attempt {attempt}: agent ({backend.name}) writing spec.yaml ...")
        out = backend.run(task)
        if not out.ok:
            log(f"  agent error: {out.error[:200]}")
        path = workdir / "spec.yaml"
        if not path.is_file():
            problems = ["spec.yaml was not written"]
            continue
        spec, problems = check_file(path)
        if spec is not None and not problems:
            res.ok, res.spec_path, res.spec, res.problems = True, path, spec, []
            return res
        log(f"  spec rejected: {len(problems)} problem(s)")
    res.problems = problems
    return res


def summary(spec: Spec) -> list[str]:
    """Human-readable key facts for the confirmation prompt."""
    pin = spec.power_input
    lines = [
        f"name: {spec.name}",
        f"input: {pin.pos_net} {pin.v_min:g} / {pin.v_nom:g} / {pin.v_max:g} V (min / nom / max)",
    ]
    for ld in spec.loads:
        lines.append(
            f"load: {ld.net} " + (f"{ld.current:g} A" if ld.current is not None else f"{ld.resistance:g} ohm")
        )
    for c in spec.acceptance:
        d = c.model_dump(exclude_none=True)
        d.pop("type", None)
        d.pop("id", None)
        lines.append(f"criterion: {c.key()} " + ", ".join(f"{k}={v}" for k, v in d.items()))
    lines.append("protection: " + (", ".join(spec.protection) or "none"))
    if spec.topology:
        lines.append(f"topology: {spec.topology.name} (designs are generated without the agent)")
    return lines
