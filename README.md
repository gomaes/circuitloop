# circuitloop

**AI-driven, autonomous circuit design for hand-soldered perfboards — with deterministic verification.**

[日本語版 README](README.ja.md)

You describe what a circuit must do (`spec.yaml`). `cloop run` asks an AI coding agent
(Claude Code or OpenCode) to write the circuit in [SKiDL](https://github.com/devbisme/skidl),
verifies it with ERC and ngspice simulation, has the agent add protection circuitry, verifies
again (including fault injection), and produces everything you need to build it on a 2.54 mm
perfboard: netlist, schematic, two-sided layout, BOM and a step-by-step soldering guide.

```
spec.yaml ─► Phase 1 minimal design ─► Phase 2 gates G1-G3 ─┐  fix loop
               (agent)                  (Python)           ◄─┘  (≤ max_iter)
          ─► Phase 3 review + protection ─► Phase 4 G1-G3 + regression + fault injection
               (agents)                      (Python, fix loop)
          ─► Phase 5 outputs: netlist · schematic · perfboard layout · BOM · build guide · report
```

## Design principles

1. **The LLM never decides pass/fail.** Every gate is deterministic Python that returns an exit
   code and a structured JSON report. The agent only *writes* `design.py` and *fixes* it from
   failure reports.
2. **The agent cannot change the criteria.** `spec.yaml`, the parts DB, rules, the checklist and
   the verifier's own source are read-only for the agent and hashed at the start of a run; any
   change after an agent step stops the run with exit code 3.
3. **The orchestrator is Python.** Loop control, state and gates live in `circuitloop`; agents are
   called for one step at a time with deny-by-default permissions (read anything, write only
   `design.py`, optionally run `cloop verify`).
4. **Bounded loops.** Each phase gets the initial attempt plus up to `max_iter` fixes (default 5);
   then a failure report is written and `cloop` exits 1.
5. **Everything is recorded.** Every attempt's prompt, agent output, design, netlist, simulation
   decks and reports are stored under `runs/<timestamp>/iter_NN/`.

## Install (Linux)

Requirements: Linux — Ubuntu 22.04/24.04 and Arch Linux (including Arch-based distributions such
as Manjaro, EndeavourOS, CachyOS) are supported; others are best effort. You also need `ngspice`
and at least one agent CLI (`claude` or `opencode`). Python 3.11+ is provided by uv if needed.

```bash
git clone https://github.com/gomaes/circuitloop.git
cd circuitloop
./install.sh          # installs uv if missing, then `uv tool install` → `cloop` on your PATH
sudo apt install ngspice   # if install.sh reports it missing (it never runs sudo itself)
cloop doctor
```

On **Arch Linux**, install the system packages with pacman first (all are in the official repos;
`install.sh` will also use a pacman-installed `uv`):

```bash
sudo pacman -S --needed git ngspice uv nodejs npm
npm install -g @anthropic-ai/claude-code      # and/or: npm install -g opencode-ai
git clone https://github.com/gomaes/circuitloop.git && cd circuitloop && ./install.sh
```

`cloop doctor` detects Arch and its derivatives from `/etc/os-release` and prints `pacman`
commands for anything missing.

`./uninstall.sh` removes the command (`--purge` also removes `~/.config/circuitloop`).

## Quick start

```bash
cloop init my_ldo --example ldo_5v     # or: cloop init my_board (blank template)
cd my_ldo
$EDITOR spec.yaml                      # optional
cloop run                              # unattended: design → verify → harden → re-verify → output
cloop status
ls output/
```

`output/` contains:

| file | content |
|---|---|
| `<name>.net` | KiCad netlist (from SKiDL) |
| `schematic.svg` | net-label schematic |
| `layout_component_side.svg`, `layout_solder_side.svg`, `layout.html` | perfboard layout, both sides (solder side mirrored), interactive HTML with hover details |
| `layout.json` | machine-readable placement and wiring |
| `bom.csv` | bill of materials with part numbers and ratings from the parts DB |
| `build_guide.md` | soldering order, solder-side wire runs, jumper list, continuity checks |
| `final_report.md/.json` | all gate results, component stress table, waveform PNGs, **items not verified** |
| `design.py` | the final SKiDL source |

## Sample output

[`docs/sample_output/`](docs/sample_output/) holds the outputs of real, unattended `cloop run`
runs with Claude Code on the three bundled examples (`examples/`): 5 V LDO supply with reverse
polarity and overcurrent protection, NE555 1 Hz LED blinker, and a single-supply ×10 op-amp. Each
passed every gate (G1–G6, including fault injection) — open `layout.html` for the interactive board.

## Commands

| command | purpose |
|---|---|
| `cloop init <name> [--example X]` | create a project (spec.yaml, cloop.toml, parts/, rules/) |
| `cloop run [spec.yaml]` | run the whole pipeline unattended |
| `cloop run --from design\|harden\|reverify\|output [--run DIR]` | resume the latest (or given) run from a phase |
| `cloop verify <design.py> [--spec] [--phase design\|final] [--baseline]` | gates only, e.g. for a hand-edited design |
| `cloop status [--json]` | progress/result of the latest run |
| `cloop doctor` | check Python, ngspice, agent CLIs; print install hints |
| `cloop parts list [--kind K] [--json]` / `cloop parts add file.yaml [--user]` | manage the parts DB |

Common options: `--agent claude|opencode`, `--max-iter N`, `--verbose`.

Exit codes: **0** success · **1** design failed (iteration limit) · **2** configuration/environment
error · **3** tampering detected.

## The specification (`spec.yaml`)

See [`src/circuitloop/templates/spec.yaml`](src/circuitloop/templates/spec.yaml) and
[`examples/`](examples/). Key sections:

- `power_input` — net names and `v_min`/`v_nom`/`v_max`; every criterion is checked at all three corners.
- `loads`, `stimuli` — attached by the simulation harness to named nets.
- `transient` — `stop`, `step`, `settle`. With a transient section, all measurements use the
  steady-state window `t ≥ settle` after a power-on start; otherwise the DC operating point is used
  (and must converge).
- `acceptance` — `dc_voltage`, `ripple`, `frequency`, `gain`, `input_power`.
- `derating` — fraction of each part's rating allowed in normal operation.
- `board` — maximum perfboard size in holes; `parts_policy` — `tht_only`, `forbidden`.
- `protection` — `reverse_polarity`, `overcurrent`, `overvoltage`, `esd`, `input_protection`.
- `faults` — conditions to inject (`reverse_polarity`, `overvoltage`) with numeric expectations;
  absolute-maximum ratings must hold. `reverse_polarity` protection without a fault entry gets a
  default fault.
- `allow_incomplete_sim` — default `false`: a part without a SPICE/equivalent model makes the
  simulation **INCOMPLETE**, which fails the gate.

Pipeline settings (agent backend, model, timeouts, `max_iter`, reviewer on/off) live in `cloop.toml`.

## Verification gates

| gate | what is checked |
|---|---|
| G1 build | `design.py` runs in an isolated subprocess (`python -I`) and writes a parseable KiCad netlist |
| G2 ERC | SKiDL ERC + plugin rules: registered parts & pinouts, parts policy, unconnected pins, single-pin nets, floating inputs, required spec nets, interface nets on connectors, decoupling per IC power pin, LED series resistors, shorted parts; protection structure (Phase 3+) |
| G3 simulation | ngspice at each supply corner: acceptance criteria and every rating (voltage, current, power) × derating; per-pin 0 V ammeters make this work for subcircuits too |
| G4 regression | Phase 1 measurements still within acceptance (optionally `regression.max_drift`) |
| G5 fault injection | reversed supply / over-voltage: net limits, input current, absolute maximum ratings |
| G6 layout | placement/routing re-extracted with union-find and compared to the netlist (opens, shorts, overlaps, board size) |

### Custom ERC rules

Drop a Python file into `<project>/rules/` (or publish an entry point in the `circuitloop.rules`
group):

```python
from circuitloop.rules import Finding, Severity, rule


@rule("project.max_resistance", "No resistor above 1 MΩ")
def check(ctx):
    return [
        Finding("project.max_resistance", Severity.ERROR, f"{c.ref} too large", refs=[c.ref])
        for c in ctx.components_of_kind("resistor")
        if (ctx.value(c) or 0) > 1e6
    ]
```

Project rules are hashed like the spec; agents cannot add or edit them.

### Parts database

YAML files in `parts/` (bundled), `~/.config/circuitloop/parts/` and `<project>/parts/`. Each part
has pins (name/type), absolute-maximum ratings, optional decoupling requirements, a perfboard
package and a SPICE model (`primitive`, `subckt`, `equivalent` or `connector`). Parts that are not
registered are an ERC error. The bundled SPICE models are circuitloop's own behavioural models of
typical datasheet behaviour — not vendor models.

## Perfboard layout

Isolated-pad 2.54 mm perfboard: parts are placed by simulated annealing, nets are routed on the
solder side with tinned-wire runs (A*), and insulated jumper wires are used where no free path
exists. Stripboard (track cutting) is not supported yet.
[boardwright](https://github.com/naam/boardwright) was evaluated but is not used: it requires
hand-placed coordinates and has no DIP/IC glyphs.

## Development

```bash
uv sync
uv run pytest -q          # gates, broken-circuit tests, mock-agent end-to-end runs (no LLM calls)
uv run ruff check . && uv run ruff format --check .
```

CI (GitHub Actions) runs lint and tests on Ubuntu 24.04 (Python 3.11–3.13, ngspice from apt) and in an
`archlinux:latest` container (system Python, ngspice from pacman), including `install.sh`.

## License

MIT. Note: SKiDL depends on InSpice (GPL-3.0-or-later), which pip/uv installs alongside
circuitloop and SKiDL loads on import. circuitloop does not use InSpice directly (simulation calls
the `ngspice` executable) and does not bundle or redistribute it.
