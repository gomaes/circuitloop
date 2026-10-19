# Contradictory fault expectations — check with the real agent (2026-10-19)

The deterministic check (`src/circuitloop/consistency.py`) was tested with Claude Code / `haiku`
on purposely contradictory conditions, besides the unit and mock-agent tests
(`tests/test_consistency.py`).

| test | setup | result |
|---|---|---|
| T1 | `cloop new` spec writing; attempt 1 is the contradictory spec from blind benchmark C2 (injected), attempt 2 onward the real agent with the check's feedback | rejected at attempt 1 with the conflict and both fixes; the agent raised `max_input_current` from 0.01 A to 1.0 A (one of the two suggested fixes), kept everything else and recorded why in `assumptions`; accepted at attempt 2 (58 s) |
| T2 | request that itself demands the C2 conditions (motor between VIN and VOUT, reversed supply: VOUT >= -0.5 V and <= 10 mA) | the spec writer put the reverse-polarity diode between the supply entry and the motor rail, which makes both conditions achievable; no conflict (correctly), the full run passed (6.7 min) |
| T3 | `cloop run` on the C2 spec written by hand | stopped at once with exit 4 and `spec_infeasible.md` (conflict and both fixes); no agent call |
| K1 | the C2 request plus "VOUT >= -0.5 V and <= 10 mA when reversed" | the writer modelled the motor to ground, which is consistent; full run passed |
| K2 | the original C2 request again (development run) | consistent spec, full run passed (5.7 min); in the blind run it had failed |

The check reported no conflict on any of the 19 other specs written during the benchmarks or the
bundled examples.
