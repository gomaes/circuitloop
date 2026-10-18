# Blind benchmark results — 2026-10-18/19

Requests: [blind_requests.md](blind_requests.md) (registered before the first run). Agent: Claude
Code with the `haiku` model, default configuration (`max_iter` 5, agent timeout 900 s,
4 self-checks), one run per request, commit `2eeb167`. No prompt, part or calculator was changed
between runs.

| id | request | result | time | where it stopped |
|---|---|---|---|---|
| B1 | Li-ion 3.7 V → 5 V / 1 A boost | **fail** | 32 min | Phase 2: VOUT ≈ 2 V at v_min = 3.0 V in every attempt |
| B2 | 12 V → 3.3 V / 300 mA | **fail** | 44 min | Phase 2: no 3.3 V regulator / buck converter possible with the parts DB |
| B3 | 1 kHz sine oscillator | **fail** | 18 min | Phase 4: only G7 (tolerance) — function, faults, regression pass |
| B4 | LM35 output × 5 into an Arduino ADC | **pass** | 2 min | all gates (topology `noninverting_amp` chosen by the spec writer) |
| B5 | 9 V, two LEDs alternating at ~2 Hz | **fail** | 13 min | Phase 4: only G7 (tolerance) — function, faults, regression pass |
| B6 | car 12 V → USB 5 V / 2 A | **fail** | 84 min | Phase 4: ripple at v_max after hardening (G3/G4/G7) |

**1 of 6 passed.** Spec writing succeeded first time in all six cases.

B3–B6 were re-run once because the first attempt ran out of disk space (each run kept every raw
waveform file, up to 7 GB per request — fixed afterwards by `loop.keep_raw = false`). The aborted
attempts are not counted.

## Causes

1. **Missing parts / topologies (B1, B2, B6).** The calculators refused correctly and said why
   (B1: no inductor rated above 3.2 A derated for the 5.4 A peak; B2: no 3.3 V regulator), and the
   agent then had to design by hand. The parts DB has no 3.3 V regulator, no buck topology, no
   high-current inductor and no MOSFET that a 3 V supply can drive via the MC34063.
2. **Spec windows tighter than the parts' tolerances (B3, B5).** The spec writer chose ±10 % for
   "~1 kHz" / "about 2 Hz", but the most precise capacitors in the DB are ±10 %, so the worst-case
   tolerance stack can never fit. The design agents noticed this themselves but had no way to
   report an infeasible spec and spent all fix attempts balancing the two corners.
3. **Hand-designed switching converter (B6).** Phase 1 passed after 5 fixes; adding protection
   raised the ripple at v_max and the fixes did not recover it.

## What this shows

- With a fitting calculator (B4, and the earlier development examples), a small model finishes
  quickly and reliably.
- Without one, Haiku produced working circuits at nominal (B3, B5, B6 Phase 1) but not designs
  that survive the full worst-case verification. The verifier did its job: none of these were
  accepted.
