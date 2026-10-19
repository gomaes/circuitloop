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
   then a failure report is written and `cloop` exits 1. A spec that the registered parts provably
   cannot meet is reported as such (exit 4) instead — see
   [When the spec asks for more than the parts allow](#when-the-spec-asks-for-more-than-the-parts-allow).
5. **Everything is recorded.** Every attempt's prompt, agent output, design, netlist, simulation
   decks and reports are stored under `runs/<timestamp>/iter_NN/`.
6. **Engineering knowledge lives in the tool, not in the model.** Design equations (topology
   calculators), root-cause analysis of failures (diagnosis) and step budgets are deterministic
   Python, so a small model only has to choose and apply them — see
   [Topology library, diagnosis and agent budget](#topology-library-diagnosis-and-agent-budget).

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

## Agent accounts and terms of use

circuitloop never handles credentials. It runs the agent CLI installed on **your** machine
(`claude -p` or `opencode run`) unmodified, and that CLI uses whatever login or API key **you**
configured. Every user must use their own account:

| backend | authentication | status |
|---|---|---|
| `claude` (Claude Code) | your own Claude Pro / Max / Team / Enterprise login (`claude` → `/login`) | OK — signing in to the unmodified Claude Code binary with your own subscription is permitted |
| `claude` (Claude Code) | your own API key (`ANTHROPIC_API_KEY`) or Bedrock / Vertex / Foundry credentials | OK — billed to the key owner |
| `opencode` | an API key for your provider (e.g. an Anthropic Console API key) | OK |
| `opencode` | Claude Pro / Max login | **Do not use** — Anthropic does not permit Claude.ai subscription login in third-party applications |

Not allowed:

- running circuitloop as a hosted service, or on other people's behalf, using **your** Pro/Max
  subscription (routing requests through subscription credentials on behalf of others);
- sharing or bundling your login, `~/.claude` credentials or session tokens.

To offer circuitloop as a service, use API-key or cloud-provider authentication under Anthropic's
Commercial Terms. Pro/Max usage limits assume ordinary individual use; a `cloop run` makes several
agent calls, so heavy automated use is better served by an API key.

See Anthropic's [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
page and the [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) /
[Commercial Terms](https://www.anthropic.com/legal/commercial-terms). This summary is not legal
advice and the terms may change — check the current versions. circuitloop is not affiliated with
or endorsed by Anthropic.

## Quick start

From a one-line request — the agent writes `spec.yaml`, you confirm it, the pipeline runs:

```bash
cloop new "USB 5 V to 12 V boost converter"      # --yes: no confirmation, --no-run: spec only
```

The agent fills everything the request leaves open (supply tolerance, load, output window,
ripple, protection, fault cases) with conventional engineering values and lists each one under
`assumptions:` — they are shown before the run starts and in the final report. The spec is
accepted only when the schema and deterministic sanity checks pass (`cloop spec check`; up to 3
attempts with the problems fed back). After confirmation it is protected like a hand-written spec:
the design agents can never change it. The project goes to `./<spec name>/`, with the request in
`request.md` and the spec-writing logs in `spec_gen/`. If the final tolerance analysis proves an
acceptance window narrower than the registered parts allow, `cloop new` widens it by the smallest
amount the verified design passes, records that under `assumptions` and finishes the run
(`--no-relax`: report only).

Or start from a template or an example and edit the spec yourself:

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
runs with Claude Code on the four bundled examples (`examples/`): 5 V LDO supply with reverse
polarity and overcurrent protection, NE555 1 Hz LED blinker, a single-supply ×10 op-amp, and a USB 5 V → 12 V / 0.5 A
boost converter (MC34063 + external MOSFET). Each
passed every gate (G1–G6, including fault injection) — open `layout.html` for the interactive board.

## Commands

| command | purpose |
|---|---|
| `cloop new "<request>" [--dir D] [--yes] [--no-run] [--no-relax]` | write `spec.yaml` from a short request (agent + deterministic checks), confirm, then run the pipeline; an infeasible tolerance window is relaxed minimally (see below) |
| `cloop spec check [spec.yaml]` | validate a spec (schema + sanity checks) and list the topologies that fit |
| `cloop init <name> [--example X]` | create a project (spec.yaml, cloop.toml, parts/, rules/) |
| `cloop run [spec.yaml] [--relax]` | run the whole pipeline unattended; `--relax`: widen an infeasible window minimally and continue |
| `cloop run --from design\|harden\|reverify\|output [--run DIR]` | resume the latest (or given) run from a phase |
| `cloop verify <design.py> [--spec] [--phase design\|final] [--baseline] [--quick]` | gates only, e.g. for a hand-edited design; `--quick` = nominal supply only, no faults (fast, not authoritative) |
| `cloop topology list [--spec S]` / `show NAME` / `generate NAME --spec S -o design.py [--set k=v] [--minimal]` | topology library: deterministic design calculators that write a complete, commented design.py |
| `cloop shopping-list [PROJECT] [--boards N] [--spares 0.1]` | everything to buy for the final design: components, IC sockets, perfboard size, wire lengths (also written to `output/shopping_list.*`) |
| `cloop status [--json]` | progress/result of the latest run |
| `cloop doctor` | check Python, ngspice, agent CLIs; print install hints |
| `cloop parts list [--kind K] [--json]` / `cloop parts add file.yaml [--user]` | manage the parts DB |

Common options: `--agent claude|opencode`, `--max-iter N`, `--jobs N`, `--verbose`.

### Parallel simulation

All simulations of one verification (every supply corner and every fault case) are independent
and run concurrently. Each ngspice process is single-threaded and small (~30 MB for the bundled
examples), so the useful number of parallel jobs is
`min(usable CPUs, number of scenarios, available memory / 300 MB)`, where usable CPUs honours the
process's CPU affinity and cgroup CPU quota (containers). Override with `--jobs N` or
`loop.sim_jobs` in `cloop.toml`. The agent loop itself is sequential by design (each fix depends
on the previous report).

Exit codes: **0** success · **1** design failed (iteration limit) · **2** configuration/environment
error · **3** tampering detected · **4** the spec cannot be met with the registered parts
(`spec_infeasible.md`, `relaxation.json`).

## The specification (`spec.yaml`)

See [`src/circuitloop/templates/spec.yaml`](src/circuitloop/templates/spec.yaml) and
[`examples/`](examples/). Key sections:

- `power_input` — net names and `v_min`/`v_nom`/`v_max`; every criterion is checked at all three corners.
- `loads`, `stimuli` — attached by the simulation harness to named nets.
- `transient` — `stop`, `step`, `settle`. With a transient section, all measurements use the
  steady-state window `t ≥ settle` after a power-on start; otherwise the DC operating point is used
  (and must converge).
- `acceptance` — `dc_voltage`, `ripple`, `frequency`, `gain`, `input_power`, `input_current`.
- `transient.save_step` / `transient.save_window_only` — resample and store only the steady-state
  window; use them for switching converters (see `examples/usb_boost_12v`).
- `derating` — fraction of each part's rating allowed in normal operation.
- `board` — maximum perfboard size in holes; `parts_policy` — `tht_only`, `forbidden`.
- `protection` — `reverse_polarity`, `overcurrent`, `overvoltage`, `esd`, `input_protection`.
- `faults` — conditions to inject (`reverse_polarity`, `overvoltage`) with numeric expectations;
  absolute-maximum ratings must hold. `reverse_polarity` protection without a fault entry gets a
  default fault.
- `tolerance` — `enabled` (default true), `method` (`worst_case` | `monte_carlo`), `samples`, `seed`.
- `allow_incomplete_sim` — default `false`: a part without a SPICE/equivalent model makes the
  simulation **INCOMPLETE**, which fails the gate.
- `assumptions` — values the request did not state (written by `cloop new`); listed in the final report.
- `topology` — optional `{name, params}`: generate the Phase 1 and hardened designs with this
  calculator instead of the agent (the agent is then only called to fix failures).

Pipeline settings (agent backend, model, timeouts, `max_iter`, reviewer on/off, `max_relax`,
`relax_rounds`) live in `cloop.toml`.

## Topology library, diagnosis and agent budget

How well an LLM designs circuits varies a lot between models. circuitloop therefore keeps the
engineering knowledge in deterministic code and leaves the model the smaller job of choosing and
adjusting:

**Topology library** (`cloop topology list --spec spec.yaml`). Each calculator derives its targets
from the spec, sizes every part with the textbook equations, selects parts from the parts DB
against the *derated* ratings, adds the protection the spec asks for and writes a complete
`design.py` with the calculations as comments:

| topology | method |
|---|---|
| `ldo_regulator` | picks the regulator whose Vout ± tolerance fits the window, whose dropout fits v_min after the protection drops and whose (Vin_max − Vout)·I + Vin·Iq fits the derated power; datasheet input/output capacitors |
| `ne555_astable` | f = 1/(ln2 (Ra + 2Rb) C) with a film timing capacitor, Ra ≈ 7 % for ~50 % duty; LED resistor from (Vcc − Voh − Vf)/I, checked at v_max and against the input-power limit |
| `noninverting_amp` | G = 1 + Rf/Rg from E24/E96, output-swing check at v_min, unused section terminated, input series resistor |
| `mc34063_boost` | ON Semi AN920: ton/toff, CT, Ipk = 2 Iout (ratio + 1), Rsc = 0.3 V / Ipk, L = 2 Lmin, Co from 9 Iout ton / Vripple and parallel low-ESR caps so Ipk·ESR ≤ Vripple/2, FB divider, MOSFET gate pull-down ≤ toff / 5 Ciss |

Agents are told which calculators fit the spec and may run `cloop topology generate` themselves
(output restricted to their `design.py`). With `topology: {name: ...}` in the spec the pipeline
generates the designs itself and never calls the agent unless a gate fails. When no topology can
meet the spec, the generator says exactly why (e.g. which regulator fails which rating). A
generated design is only a starting point: the gates decide, as always. The calculators use the
typical datasheet figures in each part's `design:` entry (Vf, ESR, Ciss, dropout, …).

**Diagnosis.** After a failed verification, deterministic diagnosers recompute the quantity behind
the failure from the netlist and those figures — 555 frequency, op-amp gain and output swing,
MC34063 set-point / current limit / gate turn-off time, ESR-dominated ripple, regulator headroom
and dissipation, LED current, series drops in the supply path, causes of aborted transients — and
add a **Diagnosis** section with the cause and a concrete value to change to the report the agent
receives. Diagnosis is advice only and never affects pass/fail.

**Agent budget.** Each agent step gets `agent.timeout` seconds (default 900) and at most
`agent.max_self_checks` `cloop verify` calls (default 4). Inside a step, `cloop verify` is always a
quick check and refuses further calls once the budget or the time is used up; the counter lives
outside the agent's work directory. Whatever `design.py` exists when the step ends is verified
authoritatively by the pipeline.

## Verification gates

| gate | what is checked |
|---|---|
| G1 build | `design.py` runs in an isolated subprocess (`python -I`) and writes a parseable KiCad netlist |
| G2 ERC | SKiDL ERC + plugin rules: registered parts & pinouts, parts policy, unconnected pins, single-pin nets, floating inputs, required spec nets, interface nets on connectors, decoupling per IC power pin, LED series resistors, shorted parts; protection structure (Phase 3+) |
| G3 simulation | ngspice at each supply corner: acceptance criteria and every rating (voltage, current, power) × derating; per-pin 0 V ammeters make this work for subcircuits too |
| G4 regression | Phase 1 measurements still within acceptance (optionally `regression.max_drift`) |
| G5 fault injection | reversed supply / over-voltage: net limits, input current, absolute maximum ratings |
| G7 tolerance | final verification only: every part value and model parameter with a tolerance (resistors ±0.1 / 1 / 5 %, capacitors ±1 / 5 / 10 / 20 %, inductors ±10–20 %, regulator/reference voltages ±1–5 %) pushed to its worst-case extreme per criterion (sensitivity-based extreme value analysis, at the supply corner with the least margin), or Monte Carlo (`tolerance.method: monte_carlo`); acceptance criteria and derated ratings must still hold |
| G6 layout | placement/routing re-extracted with union-find and compared to the netlist (opens, shorts, overlaps, board size) |

### When the spec asks for more than the parts allow

A two-sided window (`min`/`max`) can be narrower than the worst-case spread the parts' tolerances
cause — e.g. ±10 % on an RC oscillator whose capacitors are ±10 % themselves. No design can pass
that, so circuitloop does not let the agent burn its fix attempts on it. When Phase 4 fails only in
G7, a deterministic analysis (`feasibility.py`) uses G7's sensitivities to estimate the spread
with the tightest-tolerance registered part of each kind:

| verdict | meaning | what happens |
|---|---|---|
| `recenter` | the spread fits, the nominal value is off-centre | diagnosis says by how much to move it; the fix loop continues |
| `tighter_parts` | it fits with tighter registered parts | diagnosis lists them (e.g. `C4 C_FILM_100V ±10 % -> C_CER_C0G_1PCT ±1 %`); the fix loop continues |
| `infeasible` | not even the tightest registered parts fit | the run stops with **exit 4** and `spec_infeasible.md` |

`spec_infeasible.md` states the calculation and the **smallest relaxation the current design
passes**: each violated limit moves exactly to the design's verified worst-case range, rounded
outward to 0.1 % of the window centre (`relaxation.json` holds the same as data). One-sided limits
(ripple, input power/current) can always be met with more design margin and are never declared
infeasible. Design agents may also write `spec_issue.md` when they are certain a requirement cannot
be met (e.g. no registered part can do it); it is quoted, marked as unverified, in the reports.

- `cloop new` applies the relaxation automatically (turn off with `--no-relax`): it rewrites only
  those numbers in `spec.yaml` (comments kept), records the change under `assumptions`, keeps the
  previous file in `spec_history/` and continues at Phase 4 with the same design — relaxing only
  widens limits, so the Phase 1–3 results stay valid.
- `cloop run --relax` does the same for a hand-written spec, including applying the proposal of a
  run that already stopped with exit 4. Without `--relax`, `cloop run` only reports.
- A relaxation that would move a limit by more than `loop.max_relax` (default 10 % of the window
  centre) is never applied automatically; at most `loop.relax_rounds` (2) relaxations per run.

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

YAML files in `parts/` (bundled), `~/.config/circuitloop/parts/` and `<project>/parts/`.

The bundled DB (`cloop parts list`, about 145 parts) covers typical through-hole hobby parts:
resistors (metal film ±1 % 1/8–1/2 W, precision ±0.1 %, carbon film ±5 %, metal oxide 1–3 W, cement
5 W), capacitors (X7R, C0G ±5 % / ±1 %, PET ±10 % / ±5 %, PP ±5 % / ±1 %, electrolytics 6.3–100 V
and low-ESR 16–50 V up to several mF), inductors (axial chokes, 8 / 10 / 12.5 mm radial, toroids
up to 10 A), PTCs 0.1–2.5 A and 5×20 mm fuses, rectifier / Schottky / ultrafast diodes up to 10 A,
Zener (1 W, 0.5 W) and TVS (600 W, 1500 W) families by voltage, LEDs, a bridge rectifier, BJTs (BC547/557,
PN2222A/2907A, BD139/140, TIP31/32/41/42, TIP120/125), MOSFETs (2N7000, BS170, logic-level and
standard N-channel, P-channel), op-amps (LM358, LM324, TL072, NE5532, MCP6002), comparators
(LM393, LM339), 555 timers (NE555, TLC555), linear regulators (78xx 5–24 V, 78Lxx, LM2940,
LD1117 3.3/5 V, LM3940, LP2950, MCP1700, LM317), switching regulators (MC34063; LM2596 / LM2576
/ LM2575 buck, fixed 3.3 / 5 / 12 V and adjustable) and connectors.

A part family can list `sizes`: data that changes with the value — body (package/footprint),
`design:` figures and ratings — e.g. an electrolytic whose can, ESR and ripple-current rating
follow the capacitance. `{d:name}` in a SPICE line inserts such a figure (`{d:esr}`). Keys starting
with `.` are YAML-anchor templates, not parts.

Each part has pins (name/type), absolute-maximum ratings, optional decoupling requirements, a perfboard
package and a SPICE model (`primitive`, `subckt`, `equivalent` or `connector`). A model can also
come from a vendor model file you downloaded yourself — circuitloop never bundles vendor models,
whose licences often forbid redistribution:

```yaml
IRLZ44N_VENDOR:
  # ... pins, ratings, package as usual ...
  spice:
    type: subckt
    line: "X{ref} {2} {1} {3} IRLZ44N"   # node order of the vendor subcircuit
    include: models/irlz44n.lib          # relative to this YAML file (or absolute / ~)
    compat: ps                           # ngspice PSpice compatibility (ps | lt | ki)
```

Referenced model files are hashed like the parts DB; a missing file makes the simulation
INCOMPLETE. Parts that are not
registered are an ERC error. Current ratings can be checked as `peak` (default), `average`
(e.g. a diode's If(AV)) or `rms` (inductor / capacitor ripple / PTC hold current); power ratings are
thermal and are compared with the average dissipation over the steady-state window. The bundled SPICE models are circuitloop's own behavioural models of
typical datasheet behaviour — not vendor models. The optional `design:` mapping holds typical
datasheet figures (e.g. `vf`, `esr`, `ciss`, `dropout`, `vref`) used by the topology calculators
and the diagnosis — never by the pass/fail checks.

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
