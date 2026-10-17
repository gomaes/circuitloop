# Task: write the circuit specification `spec.yaml` from a short request

The person asked for:

> $request

Write `spec.yaml` in the current directory. It is the single source of truth for an automated
pipeline that designs the circuit, simulates it and decides pass/fail **only** from this file, so
every requirement must be a number the simulator can check.

## Rules

- You may write **only** `spec.yaml`. The only shell commands available are
  `cloop spec check spec.yaml` (validates your file and lists fitting topologies) and
  `cloop topology ...`. Run `cloop spec check spec.yaml` before you finish and fix everything it reports.
- Follow the schema in `ref/spec_schema.json`; `ref/spec_template.yaml` explains each field and
  `ref/examples/*.yaml` are complete, working specs — copy their structure (in particular the
  `transient` section of `usb_boost_12v.yaml` for switching converters).
- Keep the request's own words in `description`.
- **Do not invent requirements silently.** For everything the request leaves open, choose a
  conventional, conservative engineering value and record each choice in `assumptions:` as one
  short sentence (what you assumed and why), for example:
  - supply tolerance (USB: 4.75-5.25 V at the board, source_resistance 0.15 ohm for cable + charger;
    9 V battery: 7.0-9.6 V; 12 V adapter: 11-13 V),
  - output current / load, output voltage window (typically +/-5 %), ripple limit (~1 % of the
    output), frequency window, gain window,
  - input current limits of the source (USB charger: its rating, keep 10 % margin),
  - protection the use case needs (`reverse_polarity` for battery snaps and barrel jacks,
    `overcurrent` for USB and other limited sources, `input_protection` for external signal
    inputs) and matching `faults` entries with numeric expectations.
- Through-hole parts only (`parts_policy.tht_only: true`); choose a board size that fits
  (`max_cols`/`max_rows` in 2.54 mm holes, e.g. 34 x 26 for a converter).
- Only request what the parts in `ref/parts_catalog.md` can achieve; if the request is impossible
  with them, still write the closest feasible spec and say so in `assumptions`.
- If `cloop spec check` lists a fitting topology and the request does not ask for a different
  circuit, set `topology: {name: <it>}` — the pipeline then sizes the circuit deterministically.

Topologies in the library:

$topologies
$feedback
