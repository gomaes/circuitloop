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
  `ref/examples/*.yaml` show complete, working specs of other circuits (use them for the
  structure, not for the numbers of your circuit).
- Keep the request's own words in `description`.
- **Do not invent requirements silently.** For everything the request leaves open, choose a
  conventional, conservative engineering value and record each choice in `assumptions:` as one
  short sentence (what you assumed and why), for example:
  - the supply's real voltage range at the board (tolerance, battery discharge, cable drop) and
    its source resistance,
  - output current / load, output voltage window, ripple limit, frequency window, gain window,
  - input current limits of the source, with margin,
  - protection the use case needs (`reverse_polarity`, `overcurrent`, `overvoltage`,
    `input_protection`, `esd`) and matching `faults` entries with numeric expectations.
- Through-hole parts only (`parts_policy.tht_only: true`); choose a board size that fits the
  parts (`max_cols`/`max_rows` in 2.54 mm holes).
- Switching circuits need a fine `transient.step` (well below one switching period), a `settle`
  long enough for start-up and `save_step` / `save_window_only` to keep the output small.
- Only request what the parts in `ref/parts_catalog.md` can achieve; if the request is impossible
  with them, still write the closest feasible spec and say so in `assumptions`.
- Every two-sided window (`min`/`max`) must be wider than the worst-case spread the parts'
  tolerances cause, or no design can pass the final tolerance analysis. Use the tolerances in
  the catalog: an RC-timed frequency moves by about ±(R tolerance + C tolerance), a divider-set
  voltage by about ±(reference tolerance + 2 × R tolerance), plus the effect of the supply range.
  Unless the request states a tighter limit, leave at least that much plus a few percent margin.
- If `cloop spec check` lists a fitting topology and the request does not ask for a different
  circuit, set `topology: {name: <it>}` — the pipeline then sizes the circuit deterministically.

Topologies in the library:

$topologies
$feedback
