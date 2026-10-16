# Task: create a minimal circuit design (Phase 1)

Write `design.py`: a SKiDL description of a **minimal** circuit that meets the
specification below. Keep it simple — protection circuitry comes in a later phase —
but include everything needed for correct operation (decoupling capacitors required
by the parts DB, current-limiting resistors, termination of unused IC inputs).

$common

## Specification (`ref/spec.yaml`)

```yaml
$spec
```

## How to write design.py

Read `ref/skidl_guide.md` (API and a complete example) and `ref/parts_catalog.md`
(available parts, pins, ratings, decoupling requirements).

## Self-check (optional)

    cloop verify design.py --spec ref/spec.yaml --phase design --quick --out check

`--quick` simulates the nominal supply only (fast). Do not run long verifications in the
background or wait on timers: as soon as you stop, the pipeline runs the complete,
authoritative verification (all supply corners and fault cases) and reports back.

The verifier report explains every failure.
