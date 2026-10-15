# Task: design review (list weaknesses only)

You are a reviewer. Read `design.py` (a verified minimal circuit), the specification
`ref/spec.yaml`, the parts catalog `ref/parts_catalog.md` and the protection checklist
`ref/protection.md`.

Write `review.md` containing a numbered list of concrete weaknesses and risks of this
design for a hand-soldered perfboard build — robustness, protection against the
listed fault conditions, component stress, missing pull-ups/pull-downs, decoupling
placement, thermal issues, assembly mistakes it invites. For each item give a short
suggested fix using parts from the catalog.

Do **not** judge whether the design passes; that is done by a deterministic verifier.
Do not modify any file other than `review.md`.

Required protection from the spec: **$protection**
