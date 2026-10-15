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

## Self-check (optional but recommended)

    cloop verify design.py --spec ref/spec.yaml --phase $verify_phase --out check
