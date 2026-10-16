# Task: fix the design so that it passes verification ($phase_title)

The current `design.py` failed the deterministic verification gates. The full report is
in `ref/last_report.md` (summary below). Modify `design.py` to fix **every** error.
Do not remove functionality the specification requires.$extra

$common

## Verification report (summary)

$report

## Specification (`ref/spec.yaml`)

```yaml
$spec
```

Reference: `ref/skidl_guide.md`, `ref/parts_catalog.md`$extra_refs.

## Self-check (optional)

    cloop verify design.py --spec ref/spec.yaml --phase $verify_phase --quick --out check

`--quick` simulates the nominal supply only (fast). Do not run long verifications in the
background or wait on timers: as soon as you stop, the pipeline runs the complete,
authoritative verification (all supply corners and fault cases) and reports back.
