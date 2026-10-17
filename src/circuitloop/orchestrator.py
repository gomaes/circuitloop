"""Pipeline orchestrator.

The orchestrator owns the loop, the state and every gate. Agents are called as
components for single steps (generate, fix, review, harden) and never decide
whether a design passes.

    Phase 0  spec + parts DB load, integrity snapshot
    Phase 1  agent writes a minimal design.py          ┐ fix loop: initial + up to
    Phase 2  G1 build, G2 ERC, G3 simulation           ┘ max_iter fixes
    Phase 3  reviewer lists weaknesses; agent adds protection
    Phase 4  G1-G3 + G4 regression + G5 fault injection (fix loop)
    Phase 5  outputs (netlist, schematic, layout, BOM, build guide, report)

Every attempt is recorded under runs/<timestamp>/iter_NN/.
"""

from __future__ import annotations

import json
import shutil
import string
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.markup import escape

from . import EXIT_DESIGN_FAILED, EXIT_ENV_ERROR, EXIT_OK, EXIT_TAMPERED, __version__
from .agents import AgentBackend, AgentTask
from .budget import Budget, records
from .catalog import render_catalog
from .config import Config
from .gates import VerifyContext, VerifyOutcome, verify
from .integrity import Integrity, make_readonly
from .partsdb import PartsDB, PartsDBError, load_db
from .report import VerificationReport
from .resources import PKG_DIR, data_dir, prompt_path
from .results import Finding, GateResult, Severity, Status
from .spec import Spec, SpecError, load_spec

PHASES = ("design", "harden", "reverify", "output")
PHASE_ALIASES = {"1": "design", "2": "design", "3": "harden", "4": "reverify", "5": "output"}


class PipelineStop(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RunState:
    run_dir: str
    spec: str
    project: str
    agent: str
    version: str = __version__
    status: str = "running"  # running | passed | failed | tampered | error
    message: str = ""
    started: str = ""
    finished: str = ""
    current_phase: str = ""
    phases: dict = field(default_factory=dict)
    iterations: list = field(default_factory=list)
    final_design: str | None = None
    outputs: list = field(default_factory=list)

    @classmethod
    def load(cls, run_dir: Path) -> RunState:
        return cls(**json.loads((run_dir / "state.json").read_text()))

    def save(self) -> None:
        Path(self.run_dir, "state.json").write_text(json.dumps(self.__dict__, indent=2, default=str))


def latest_run(project_dir: Path) -> Path | None:
    runs = sorted(p for p in (project_dir / "runs").glob("*") if (p / "state.json").is_file())
    return runs[-1] if runs else None


def _tmpl(name: str, **kw) -> str:
    return string.Template(prompt_path(name).read_text()).safe_substitute(**kw)


class Orchestrator:
    def __init__(
        self,
        spec_path: Path,
        cfg: Config,
        agent: AgentBackend,
        console: Console | None = None,
        verbose: bool = False,
    ):
        self.spec_path = spec_path.resolve()
        self.project = self.spec_path.parent
        self.cfg = cfg
        self.agent = agent
        self.console = console or Console()
        self.verbose = verbose
        self.spec: Spec
        self.db: PartsDB
        self.integrity = Integrity()
        self.state: RunState
        self.run_dir: Path

    # ------------------------------------------------------------------ setup
    def _log(self, msg: str) -> None:
        self.console.print(msg)

    def _load(self) -> None:
        try:
            self.spec = load_spec(self.spec_path)
        except SpecError as e:
            raise PipelineStop(EXIT_ENV_ERROR, str(e)) from e
        try:
            self.db = load_db(self.project)
        except PartsDBError as e:
            raise PipelineStop(EXIT_ENV_ERROR, f"parts DB error: {e}") from e
        if shutil.which("ngspice") is None:
            raise PipelineStop(EXIT_ENV_ERROR, "ngspice not found (run `cloop doctor`)")
        if not self.agent.available():
            raise PipelineStop(
                EXIT_ENV_ERROR, f"agent CLI '{self.agent.executable}' not found (run `cloop doctor`)"
            )

    def _protect(self) -> None:
        """Phase 0: snapshot everything the agent must not change."""
        self.integrity = Integrity()
        self.integrity.add(self.spec_path)
        cfg_file = self.project / "cloop.toml"
        if cfg_file.is_file():
            self.integrity.add(cfg_file)
        self.integrity.add(*self.db.files)
        model_files = [f for f in self.db.model_files() if f.is_file()]
        if model_files:  # vendor model files referenced by the parts DB
            self.integrity.add(*model_files)
        for d in (self.project / "parts", self.project / "rules"):
            if d.is_dir():
                self.integrity.add(d)
        self.integrity.add(data_dir("checklists"), PKG_DIR)
        self.integrity.save(self.run_dir / "protected_hashes.json")

    def _check_integrity(self, where: str) -> None:
        problems = self.integrity.check()
        if problems:
            (self.run_dir / "TAMPER_REPORT.md").write_text(
                "# Tampering detected\n\n"
                f"After: {where}\n\nProtected files changed (spec, parts DB, rules, verifier or read-only "
                "copies). The run was stopped.\n\n" + "\n".join(f"- {p}" for p in problems) + "\n"
            )
            raise PipelineStop(EXIT_TAMPERED, f"tampering detected after {where}: {problems[0]}")

    def _new_run(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = self.project / "runs" / stamp
        run_dir, n = base, 1
        while run_dir.exists():
            n += 1
            run_dir = base.with_name(f"{stamp}-{n}")
        run_dir.mkdir(parents=True)
        self.run_dir = run_dir
        shutil.copy(self.spec_path, run_dir / "spec.yaml")
        self.state = RunState(
            run_dir=str(run_dir),
            spec=str(self.spec_path),
            project=str(self.project),
            agent=self.agent.name,
            started=datetime.now().isoformat(timespec="seconds"),
        )
        self.state.save()

    # ------------------------------------------------------------- public API
    def run(self, start: str = "design", run_dir: Path | None = None) -> int:
        start = PHASE_ALIASES.get(start, start)
        if start not in PHASES:
            self._log(f"[red]unknown phase '{start}'[/] (choose from {', '.join(PHASES)})")
            return EXIT_ENV_ERROR
        try:
            self._load()
            if start == "design":
                self._new_run()
            else:
                rd = run_dir or latest_run(self.project)
                if rd is None:
                    raise PipelineStop(EXIT_ENV_ERROR, "no previous run to resume (runs/ is empty)")
                self.run_dir = rd.resolve()
                self.state = RunState.load(self.run_dir)
                self.state.status, self.state.message = "running", f"resumed from {start}"
            self._protect()
            self._log(f"[bold]circuitloop[/] run [cyan]{self.run_dir}[/] (agent: {self.agent.name})")
            order = PHASES[PHASES.index(start) :]
            design_p1 = self._phase_design() if "design" in order else self._resume_design("design")
            if "harden" in order:
                hardened = self._phase_harden(design_p1)
            elif "reverify" in order:
                hardened = self._resume_design("harden")
            if "reverify" in order:
                final, outcome = self._phase_reverify(hardened)
            else:
                final = self._resume_design("reverify")
                outcome = None
            self._phase_output(final, outcome)
            self.state.status, self.state.message = "passed", "all phases passed"
            self._log(f"[green bold]PASSED[/] — outputs in {self.project / 'output'}")
            return EXIT_OK
        except PipelineStop as e:
            if hasattr(self, "state"):
                self.state.status = {EXIT_TAMPERED: "tampered", EXIT_DESIGN_FAILED: "failed"}.get(
                    e.code, "error"
                )
                self.state.message = e.message
            color = "red" if e.code != EXIT_ENV_ERROR else "yellow"
            self._log(f"[{color} bold]STOPPED[/] ({e.code}): {escape(e.message)}")
            return e.code
        finally:
            if hasattr(self, "state"):
                self.state.finished = datetime.now().isoformat(timespec="seconds")
                self.state.save()

    # ----------------------------------------------------------------- phases
    def _resume_design(self, phase: str) -> Path:
        info = self.state.phases.get(phase, {})
        if info.get("status") != "passed" or not info.get("design"):
            raise PipelineStop(
                EXIT_ENV_ERROR, f"cannot resume: phase '{phase}' has no passed design in this run"
            )
        return Path(info["design"])

    def _phase_design(self) -> Path:
        self._enter("design")
        design: Path | None = None
        report: VerificationReport | None = None
        generated = self._generate("design", protect=False)
        for attempt in range(self.cfg.loop.max_iter + 1):
            if attempt == 0 and generated is not None:
                it, work = generated
            else:
                if attempt == 0:
                    instr = _tmpl(
                        "design.md",
                        spec=self._spec_text(),
                        common=self._common(["design.py"]),
                        topologies=self._topology_text(minimal=True),
                    )
                else:
                    instr = self._fix_prompt(report, "Phase 2 — design verification", "design")
                it, work = self._agent_step("design", "designer", instr, design, report, attempt)
            design, outcome = self._verify_step(it, work, phase=1)
            report = outcome.report
            if report.passed:
                baseline = self.run_dir / "baseline.json"
                baseline.write_text(json.dumps(outcome.measurements, indent=2))
                self._pass("design", design, extra={"baseline": str(baseline)})
                return design
        self._fail("design", report)
        raise AssertionError("unreachable")

    def _phase_harden(self, design_p1: Path) -> Path:
        self._enter("harden")
        generated = self._generate("harden", protect=True)
        if generated is not None:  # deterministic: the topology adds the spec's protection itself
            it, work = generated
            snap = Path(it) / "design.py"
            shutil.copy(work / "design.py", snap)
            self._harden_refs = {}
            self._pass("harden", snap)
            return snap
        review_note = ""
        refs_extra: dict[str, str] = {}
        if self.cfg.loop.review:
            review = self._review(design_p1)
            if review:
                refs_extra["review.md"] = review
                review_note = (
                    "\nA separate reviewer listed weaknesses in `ref/review.md`. Treat them as "
                    "suggestions: fix what is relevant; the verifier alone decides pass/fail.\n"
                )
        instr = _tmpl(
            "harden.md",
            protection=", ".join(self.spec.protection) or "(none listed — apply general good practice)",
            faults=self._faults_text(),
            review_note=review_note,
            common=self._common(["design.py"]),
            spec=self._spec_text(),
            extra_refs=", `ref/review.md`" if review_note else "",
            topologies=self._topology_text(minimal=False),
        )
        self._harden_refs = refs_extra
        it, work = self._agent_step("harden", "designer", instr, design_p1, None, 0, refs_extra)
        cand = work / "design.py"
        if not cand.is_file():
            cand = design_p1
        snap = Path(it) / "design.py"
        shutil.copy(cand, snap)
        self._pass("harden", snap)
        return snap

    def _phase_reverify(self, design: Path) -> tuple[Path, VerifyOutcome]:
        self._enter("reverify")
        baseline = json.loads((self.run_dir / "baseline.json").read_text())
        refs = getattr(self, "_harden_refs", {})
        report: VerificationReport | None = None
        for attempt in range(self.cfg.loop.max_iter + 1):
            if attempt > 0:
                instr = self._fix_prompt(
                    report, "Phase 4 — re-verification after hardening", "final", harden=True
                )
                it, _work = self._agent_step("reverify", "designer", instr, design, report, attempt, refs)
            else:
                it = self._iter_dir("reverify", "verify")
                shutil.copy(design, it / "design.py")
            design, outcome = self._verify_step(
                it, it / "work" if attempt else it, phase=3, baseline=baseline
            )
            report = outcome.report
            if report.passed:
                self._pass("reverify", design)
                self.state.final_design = str(design)
                return design, outcome
        self._fail("reverify", report)
        raise AssertionError("unreachable")

    def _phase_output(self, design: Path, outcome: VerifyOutcome | None) -> None:
        from .export import export_all

        self._enter("output")
        if outcome is None:  # resumed: re-run the full verification to get fresh data
            baseline = json.loads((self.run_dir / "baseline.json").read_text())
            it = self._iter_dir("output", "verify")
            shutil.copy(design, it / "design.py")
            _, outcome = self._verify_step(it, it, phase=3, baseline=baseline)
            if not outcome.report.passed:
                self._fail("output", outcome.report)
        out_dir = self.project / "output"
        result = export_all(design, outcome, self.spec, self.db, out_dir, self.run_dir)
        self.state.outputs = [str(p) for p in result.files]
        if not result.ok:
            rep = VerificationReport(design=str(design), phase="Phase 5 — outputs")
            rep.gates.append(GateResult("G6", "layout", Status.FAIL, result.findings))
            self._fail("output", rep)
        run_out = self.run_dir / "output"
        if run_out.exists():
            shutil.rmtree(run_out)
        shutil.copytree(out_dir, run_out)
        self._pass("output", design)

    # --------------------------------------------------------------- helpers
    def _enter(self, phase: str) -> None:
        self.state.current_phase = phase
        self.state.phases.setdefault(phase, {})["status"] = "running"
        self.state.save()
        self._log(f"\n[bold blue]== phase: {phase} ==[/]")

    def _pass(self, phase: str, design: Path, extra: dict | None = None) -> None:
        self.state.phases[phase] = {"status": "passed", "design": str(design), **(extra or {})}
        self.state.save()
        self._log(f"[green]phase {phase} passed[/]")

    def _fail(self, phase: str, report: VerificationReport | None) -> None:
        self.state.phases[phase] = {"status": "failed"}
        path = self._failure_report(phase, report)
        raise PipelineStop(
            EXIT_DESIGN_FAILED, f"phase '{phase}' did not pass within the iteration limit; see {path}"
        )

    def _iter_dir(self, phase: str, role: str) -> Path:
        n = 1 + max([int(p.name[5:]) for p in self.run_dir.glob("iter_*") if p.name[5:].isdigit()] or [0])
        d = self.run_dir / f"iter_{n:02d}"
        d.mkdir()
        meta = {
            "iter": n,
            "phase": phase,
            "role": role,
            "started": datetime.now().isoformat(timespec="seconds"),
        }
        (d / "meta.json").write_text(json.dumps(meta, indent=2))
        self.state.iterations.append({"dir": str(d), "phase": phase, "role": role})
        self.state.save()
        return d

    def _workspace(self, it: Path, design: Path | None, extra: dict[str, str], design_readonly: bool) -> Path:
        work = it / "work"
        ref = work / "ref"
        ref.mkdir(parents=True)
        shutil.copy(self.spec_path, ref / "spec.yaml")
        (ref / "parts_catalog.md").write_text(render_catalog(self.db))
        (ref / "skidl_guide.md").write_text(prompt_path("skidl_guide.md").read_text())
        (ref / "protection.md").write_text((data_dir("checklists") / "protection.md").read_text())
        for name, text in extra.items():
            (ref / name).write_text(text)
        if design is not None and design.is_file():
            shutil.copy(design, work / "design.py")
            (work / "design.py").chmod(0o444 if design_readonly else 0o644)
        make_readonly(ref)
        self.integrity.add(ref)
        if design_readonly and (work / "design.py").exists():
            self.integrity.add(work / "design.py")
        return work

    def _agent_step(
        self,
        phase: str,
        role: str,
        instructions: str,
        design: Path | None,
        report: VerificationReport | None,
        attempt: int,
        extra: dict[str, str] | None = None,
    ) -> tuple[Path, Path]:
        it = self._iter_dir(phase, role)
        refs = dict(extra or {})
        if report is not None:
            refs["last_report.md"] = report.to_markdown()
        work = self._workspace(it, design, refs, design_readonly=False)
        label = "generate" if attempt == 0 else f"fix #{attempt}"
        self._log(f"  \\[{it.name}] agent ({self.agent.name}) {role}: {label} ...")
        task = self._task(role, instructions, work, ["design.py"], it)
        res = self.agent.run(task)
        used = len(records(it / "agent" / "self_checks.json"))
        self._log(
            f"  \\[{it.name}] agent finished in {res.duration_s:.0f}s"
            + f" ({used}/{self.cfg.agent.max_self_checks} self-checks)"
            + ("" if res.ok else f" [yellow](agent error: {escape(res.error[:200])})[/]")
        )
        self._check_integrity(f"{it.name} ({phase} {role})")
        return it, work

    def _task(self, role: str, instructions: str, work: Path, writable: list[str], it: Path) -> AgentTask:
        timeout = self.cfg.agent.timeout
        b = Budget(self.cfg.agent.max_self_checks, it / "agent" / "self_checks.json", time.time() + timeout)
        return AgentTask(role, instructions, work, writable, it / "agent", timeout, env=b.env(work))

    def _verify_step(
        self, it: Path, work: Path, phase: int, baseline: dict | None = None
    ) -> tuple[Path, VerifyOutcome]:
        src = work / "design.py"
        snap = it / "design.py"
        if src.is_file() and src.resolve() != snap.resolve():
            shutil.copy(src, snap)
        if not snap.is_file():
            rep = VerificationReport(design=str(snap), phase=f"phase {phase}")
            rep.gates.append(
                GateResult(
                    "G1",
                    "build (design.py -> netlist)",
                    Status.FAIL,
                    [Finding("agent.no_design", Severity.ERROR, "the agent did not produce design.py")],
                )
            )
            rep.write(it)
            self._log(f"  \\[{it.name}] [red]no design.py produced[/]")
            return snap, VerifyOutcome(rep)
        ctx = VerifyContext(
            self.spec,
            self.db,
            self.project,
            design_timeout=self.cfg.loop.design_timeout,
            sim_timeout=self.cfg.loop.sim_timeout,
            sim_jobs=self.cfg.loop.sim_jobs,
        )
        t0 = time.monotonic()
        outcome = verify(
            snap,
            it / "verify",
            ctx,
            phase=phase,
            baseline=baseline,
            faults=phase >= 3,
            phase_label="Phase 2 — design verification" if phase == 1 else "Phase 4 — re-verification",
        )
        outcome.report.write(it)
        self._check_integrity(f"{it.name} verification")
        summary = ", ".join(f"{g.gate}:{g.status}" for g in outcome.report.gates)
        color = "green" if outcome.report.passed else "red"
        self._log(f"  \\[{it.name}] gates ({time.monotonic() - t0:.0f}s): [{color}]{summary}[/]")
        if self.verbose and not outcome.report.passed:
            for g in outcome.report.gates:
                for f in g.errors()[:8]:
                    self._log(f"      {g.gate} {f.rule}: {escape(f.message.splitlines()[0])}")
        meta = json.loads((it / "meta.json").read_text())
        meta.update(finished=datetime.now().isoformat(timespec="seconds"), passed=outcome.report.passed)
        (it / "meta.json").write_text(json.dumps(meta, indent=2))
        return snap, outcome

    def _review(self, design: Path) -> str | None:
        it = self._iter_dir("harden", "reviewer")
        work = self._workspace(it, design, {}, design_readonly=True)
        instr = _tmpl("review.md", protection=", ".join(self.spec.protection) or "(none)")
        self._log(f"  \\[{it.name}] agent ({self.agent.name}) reviewer ...")
        res = self.agent.run(self._task("reviewer", instr, work, ["review.md"], it))
        self._check_integrity(f"{it.name} (review)")
        rv = work / "review.md"
        if not rv.is_file():
            self._log(
                f"  \\[{it.name}] [yellow]reviewer produced no review.md ({escape(res.error[:120])})[/]"
            )
            return None
        shutil.copy(rv, it / "review.md")
        return rv.read_text()

    def _generate(self, phase: str, protect: bool) -> tuple[Path, Path] | None:
        """Write the design from spec.topology (no agent). None when no hint is set or it fails."""
        from .topologies import TopologyError, generate

        hint = self.spec.topology
        if hint is None:
            return None
        it = self._iter_dir(phase, "topology")
        work = it / "work"
        work.mkdir()
        try:
            gen = generate(hint.name, self.spec, self.db, hint.params, protect=protect)
        except TopologyError as e:
            (it / "topology_error.txt").write_text(str(e) + "\n")
            self._log(
                f"  \\[{it.name}] [yellow]topology {hint.name} failed: {escape(str(e))}[/] — using the agent"
            )
            return None
        (work / "design.py").write_text(gen.text)
        variant = "with protection" if protect else "minimal"
        self._log(f"  \\[{it.name}] design generated by topology [bold]{hint.name}[/] ({variant}, no agent)")
        return it, work

    def _topology_text(self, minimal: bool) -> str:
        """Topology-library section for the agent prompt: which calculators fit this spec."""
        from .topologies import TOPOLOGIES, TopologyError, generate

        flag = " --minimal" if minimal else ""
        lines = []
        for name, top in TOPOLOGIES.items():
            if top.applicable(self.spec) is not None:
                continue
            try:
                generate(name, self.spec, self.db, protect=not minimal)
            except TopologyError as e:
                lines.append(f"- `{name}` — {top.summary}. Does not work here: {e}")
                continue
            lines.append(
                f"- `{name}` — {top.summary}:\n\n      cloop topology generate {name} --spec ref/spec.yaml -o design.py{flag}\n"
            )
        if not lines:
            return (
                "No calculator in the topology library fits this spec (`cloop topology list --spec "
                "ref/spec.yaml`); write design.py by hand."
            )
        head = (
            "These deterministic design calculators fit this spec. Each sizes every part with the "
            "textbook equations, picks parts against the derated ratings and writes a complete "
            "`design.py` with the calculations as comments:\n\n"
        )
        tail = (
            "\nGenerating from a topology and then checking it is the most reliable way to a passing "
            "design; change only what the verification report asks for. Parameters can be set with "
            "`--set name=value` (`cloop topology show NAME` explains them)."
        )
        if not minimal:
            tail += (
                " Without `--minimal` the generator already adds the protection the spec lists; if the "
                "current design.py came from a topology, regenerating it is usually the best start."
            )
        return head + "\n".join(lines) + tail

    def _spec_text(self) -> str:
        return self.spec_path.read_text().strip()

    def _common(self, writable: list[str]) -> str:
        return _tmpl(
            "common.md",
            writable=", ".join(f"`{w}`" for w in writable),
            self_checks=self.cfg.agent.max_self_checks,
            minutes=max(1, round(self.cfg.agent.timeout / 60)),
            pos_net=self.spec.power_input.pos_net,
            ground_net=self.spec.ground_net,
        )

    def _faults_text(self) -> str:
        faults = self.spec.effective_faults()
        if not faults:
            return "- (none)"
        lines = []
        for f in faults:
            v = f.voltage if f.voltage is not None else self.spec.power_input.v_nom
            desc = "supply connected reversed" if f.kind == "reverse_polarity" else "input over-voltage"
            exp = yaml.safe_dump(f.expect.model_dump(exclude_none=True), default_flow_style=True).strip()
            lines.append(f"- `{f.name}`: {desc} at {v:g} V; expectations: {exp}")
        return "\n".join(lines)

    def _fix_prompt(
        self, report: VerificationReport | None, title: str, verify_phase: str, harden: bool = False
    ) -> str:
        text = report.to_markdown() if report else "(no report)"
        if len(text) > 12000:
            text = text[:12000] + "\n... (truncated; see ref/last_report.md)"
        extra = ""
        if harden:
            extra = (
                f"\nThe design must keep the protection required by the spec "
                f"({', '.join(self.spec.protection) or 'none'}) and survive these faults:\n\n"
                + self._faults_text()
            )
        refs = getattr(self, "_harden_refs", {}) if harden else {}
        return _tmpl(
            "fix.md",
            phase_title=title,
            report=text,
            spec=self._spec_text(),
            common=self._common(["design.py"]),
            extra=extra,
            verify_phase=verify_phase,
            extra_refs=", `ref/protection.md`" + (", `ref/review.md`" if "review.md" in refs else "")
            if harden
            else "",
        )

    def _failure_report(self, phase: str, report: VerificationReport | None) -> Path:
        lines = [
            f"# circuitloop: phase '{phase}' failed",
            "",
            f"The design did not pass within {self.cfg.loop.max_iter} fix attempt(s).",
            "",
            "## Attempts",
            "",
            "| iteration | role | result | errors (first) |",
            "|---|---|---|---|",
        ]
        for entry in self.state.iterations:
            if entry["phase"] != phase:
                continue
            d = Path(entry["dir"])
            rj = d / "report.json"
            if rj.is_file():
                data = json.loads(rj.read_text())
                errs = [
                    f"{g['gate']} {f['rule']}"
                    for g in data["gates"]
                    for f in g["findings"]
                    if f["severity"] == "error"
                ]
                res = "passed" if data["passed"] else f"failed ({len(errs)} errors)"
                first = "; ".join(errs[:3])
            else:
                res, first = "no report", ""
            lines.append(f"| {d.name} | {entry['role']} | {res} | {first} |")
        if report is not None:
            counts: dict[str, int] = {}
            for g in report.gates:
                for f in g.errors():
                    counts[f.rule] = counts.get(f.rule, 0) + 1
            lines += ["", "## Remaining problems (last attempt)", ""]
            lines += [f"- `{r}` × {n}" for r, n in sorted(counts.items(), key=lambda x: -x[1])]
            lines += ["", "## Last verification report", "", report.to_markdown()]
        path = self.run_dir / "failure_report.md"
        path.write_text("\n".join(lines) + "\n")
        (self.run_dir / "failure_report.json").write_text(
            json.dumps(
                {
                    "phase": phase,
                    "max_iter": self.cfg.loop.max_iter,
                    "last_report": report.to_dict() if report else None,
                },
                indent=2,
                default=str,
            )
        )
        return path
