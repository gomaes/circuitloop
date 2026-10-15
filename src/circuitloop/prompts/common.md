## Ground rules (read carefully)

- You are one step in an automated pipeline. A deterministic verifier (not you, not
  another model) decides whether the design passes. You cannot change the pass criteria.
- You may write **only**: $writable. Everything under `ref/` is read-only reference
  material. Any modification of `ref/`, the spec, the parts database, rules or the
  verifier is detected by hash and aborts the whole run as tampering.
- Use **only** parts listed in `ref/parts_catalog.md`, instantiated with
  `part("<KEY>", value, ref=...)`. Never create SKiDL `Part` objects yourself and never
  invent pin numbers — use the pin names from the catalog.
- Through-hole parts only; the board is a 2.54 mm perfboard soldered by hand.
- The simulation harness connects the power supply between net `$pos_net` and net
  `$ground_net`, and attaches the loads/stimuli listed in the spec to the named nets.
  Name these nets exactly as written in the spec.
- Every rating in the parts DB is checked in simulation against the derating factors in
  the spec (normal operation) and against absolute maximum values (fault injection).
