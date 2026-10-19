## Ground rules (read carefully)

- You are one step in an automated pipeline. A deterministic verifier (not you, not
  another model) decides whether the design passes. You cannot change the pass criteria.
- You may write **only**: $writable — use the Edit/Write tools on that file. The only
  shell commands available are `cloop verify ...` and `cloop topology ...` (one command, no
  `cd`, pipes or scripts); anything else is denied. To inspect results, read the files
  `cloop verify` writes (`report.md`, `sim/*/ngspice.log`) with the Read tool.
- **Budget for this step: at most $self_checks `cloop verify` self-checks and about
  $minutes minutes.** Further self-checks are refused and the step is cut off at the time
  limit; whatever `design.py` then contains is verified by the pipeline. Think first, then
  check — do not iterate by trial and error.
- Everything under `ref/` is read-only reference material. Any modification of `ref/`, the spec, the parts database, rules or the
  verifier is detected by hash and aborts the whole run as tampering.
- Use **only** parts listed in `ref/parts_catalog.md`, instantiated with
  `part("<KEY>", value, ref=...)`. Never create SKiDL `Part` objects yourself and never
  invent pin numbers — use the pin names from the catalog.
- Through-hole parts only; the board is a 2.54 mm perfboard soldered by hand.
- The simulation harness connects the power supply between net `$pos_net` and net
  `$ground_net`, and attaches the loads/stimuli listed in the spec to the named nets.
  Name these nets exactly as written in the spec.
- Bring every external connection (supply `$pos_net`/`$ground_net`, loads, input/output
  signals) out to a connector pin (terminal block or pin header) — the board must be wireable.
- Every rating in the parts DB is checked in simulation against the derating factors in
  the spec (normal operation) and against absolute maximum values (fault injection).
- The final verification also runs a **worst-case tolerance analysis**: every part value
  and model parameter with a tolerance in the catalog (e.g. resistors ±1 %, ceramics ±10 %,
  electrolytics/inductors ±20 %, regulator/reference voltages ±2-5 %) is pushed to the
  extreme that hurts each criterion. Design with margin: a nominal value just inside a
  limit will fail. Prefer tighter parts where precision matters (film instead of
  electrolytic capacitors for timing).
- If you are **certain** the specification cannot be met with the parts in the catalog (not
  merely hard — e.g. no registered part can do it, or the window is narrower than the parts'
  tolerances), say so honestly in `spec_issue.md`: which requirement, the calculation that
  shows it, and the smallest change to the spec that would make it achievable. The pipeline
  passes it on to the person. It does not change pass/fail, so still deliver the best
  `design.py` you can.
