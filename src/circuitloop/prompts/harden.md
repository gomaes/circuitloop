# Task: harden the design with protection circuitry (Phase 3)

`design.py` contains a verified minimal design. Improve its robustness **without
breaking its function** (the original acceptance criteria are re-checked, and a
regression check compares against the current behaviour).

Required protection (from the spec): **$protection**

Fault conditions that will be simulated (the protection must work numerically,
and no part may exceed its absolute maximum ratings):

$faults

Use `ref/protection.md` as a checklist (reverse-polarity protection, fuse/PTC,
TVS, input series resistors, pull-ups/pull-downs, bulk capacitance, ...). Apply
what is relevant to this circuit; every added part must be justified.
$review_note

$common

## Specification (`ref/spec.yaml`)

```yaml
$spec
```

Reference: `ref/skidl_guide.md`, `ref/parts_catalog.md`, `ref/protection.md`$extra_refs.

## Self-check (optional but recommended)

    cloop verify design.py --spec ref/spec.yaml --phase final --out check
