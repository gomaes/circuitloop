# Blind benchmark 2 — results (2026-10-19)

Requests: [blind2_requests.md](blind2_requests.md), registered before the first run (commit
`745d336`, code `4267a17`). One run per request with `cloop new "<request>" --yes`, default
configuration. Two runs at a time on a 4-CPU machine (the three C4 runs in the same lane).
Nothing was changed between runs.

Tokens are the agent CLI's own usage report summed over every agent call of the run (spec
writer, designer, reviewer): *new* = input + cache writes + output, *cache reads* listed
separately (they dominate the total and are billed at a fraction of the input price).

## Haiku, all requests

| id | request | result | wall | agent | verify | agent calls | fix attempts | where it got stuck | new tokens | cache reads | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | USB 5 V → 3.3 V for ESP32 (500 mA) | **pass** | 6.7 min | 4.6 min | 4 s | 5 | 1 | calculator found no regulator with margin (LD1117 dropout); hand design, 1 fix (G3) | 349 k | 2.69 M | $0.12 |
| C2 | Arduino pin switches a 12 V 1 A motor | fail | 15.8 min | 14.4 min | 13 s | 9 | 5 | Phase 4, G5 in every attempt — the spec's reverse-polarity limits contradict each other (see below) | 677 k | 3.60 M | $0.25 |
| C3 | 9 V, mic signal ×100 | fail | 28.5 min | 28.2 min | 17 s | 6 | 5 | Phase 1, G3 output ≈ 0 V in every attempt — **op-amp model defect** (see below) | 843 k | 6.86 M | $0.86 |
| C4 | 24 V → 5 V 1 A | **pass** | 8.9 min | 5.5 min | 100 s | 5 | 1 | G7: ripple at v_max with tolerances, fixed in 1 | 334 k | 2.80 M | $0.12 |
| C5 | 12 V battery < 11 V → red LED | **pass** | 6.1 min | 3.9 min | 4 s | 4 | 0 | — | 259 k | 1.97 M | $0.09 |
| C6 | 5 V, ~2 kHz buzzer square wave | **pass** | 4.9 min | 3.1 min | 12 s | 4 | 1 | calculator design missed a connector for OUT (G2), fixed in 1 | 217 k | 1.66 M | $0.07 |

**4 of 6 passed** (first blind benchmark: 1 of 6). Every spec was accepted at the first attempt.
No run needed a spec relaxation. Agent time dominates; verification is seconds except for the
switching converter (C4, ~2 min).

## Model comparison (C4, one run each)

| model | result | wall | agent | verify | agent calls | fix attempts | stuck at | new tokens | cache reads | output tokens | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku | pass | 8.9 min | 5.5 min | 100 s | 5 | 1 | G7 ripple at v_max | 334 k | 2.80 M | 68 k | $0.12 |
| sonnet | pass | 5.5 min | 3.0 min | 55 s | 5 | 1 | G3: input cap 35 V part at 30 V (> 28 V derated) | 193 k | 1.49 M | 23 k | $1.06 |
| opus | pass | 7.2 min | 4.1 min | 60 s | 4 | 0 | — | 183 k | 1.53 M | 24 k | $2.06 |

All three pass. Haiku needs about twice the tokens (3× the output) of the larger models but is
9× cheaper than Sonnet and 17× cheaper than Opus; Opus is the only one with no fix attempt.
One run per model: these are single samples, not averages.

## Where it got stuck

- **C3 — circuitloop defect.** The behavioural op-amp model (`CL_OPAMP`, also `CL_OPAMP2`) has
  an unbounded internal integrator. During power-up the inputs are briefly unbalanced, the
  internal node winds up to a large negative voltage, and the output then needs ~50 ms to
  recover — longer than the 20 ms simulation. The final design was correct (mid-rail bias, AC
  coupling, +40 mV across the inputs) and the output still read 0 V. No agent could have fixed
  this; it was spent on five 4-7-minute attempts.
- **C2 — infeasible spec from the spec writer, reported honestly by the design agent.** For a
  low-side switch the motor sits between VIN and VOUT, so with the supply reversed
  `VOUT >= -0.5 V` and `input current <= 10 mA` cannot both hold. The design agent showed this
  with KCL in `spec_issue.md` in four attempts; the report quotes it. Automatic relaxation only
  covers tolerance windows (G7), not fault expectations, so the run used up its attempts.
- **C6 — calculator defect.** `ne555_astable` without an LED did not bring OUT to a connector;
  the agent fixed it in one attempt.
- **C1** — the LDO calculator correctly found no registered regulator with margin (LD1117
  dropout at 4.75 V input after the reverse-polarity diode); the agent used an LM3940 by hand.
