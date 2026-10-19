"""Can a failing acceptance window be met at all with the registered parts?

G7 (worst-case tolerance analysis) records, for every toleranced quantity, how much it moves each
criterion at +tolerance, plus the criterion values at the supply corners. From that this module
estimates, per two-sided window that fails G7, the smallest worst-case spread the circuit could reach
if every part were replaced by the tightest-tolerance alternative of its kind in the parts DB:

    spread_best = corner spread + tolerance spread * sum(|effect_i| * best_tol_i / tol_i) / sum(|effect_i|)

and compares it with the window width:

    recenter       the design's own spread already fits: shift the nominal value
    tighter_parts  it fits with tighter parts that are registered (they are listed)
    infeasible     not even the tightest registered parts fit: the spec asks for more than this circuit
                   and the parts DB can deliver

For infeasible windows the minimal relaxation is the window that just covers the verified worst-case
range of the current design (rounded outward to 0.1 % of the window centre), so the same design passes
it unchanged. One-sided limits (ripple, input power/current) can always be improved by the design, so
they are never declared infeasible. The analysis is linear (like G7's sensitivity step) and only
advises: pass/fail stays with the gates.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .partsdb import PartDef, PartsDB
from .report import VerificationReport
from .results import Severity, Status
from .spec import Spec
from .units import parse_value

# replacing a part by one of the same group keeps the circuit (a film cap for an electrolytic, ...)
_GROUPS = {"capacitor": ("capacitor", "electrolytic"), "electrolytic": ("capacitor", "electrolytic")}


@dataclass
class Upgrade:
    ref: str
    what: str  # "value" or a model parameter name
    part: str
    tolerance: float
    alternative: str
    alt_tolerance: float

    def text(self) -> str:
        what = "" if self.what == "value" else f".{self.what}"
        return (
            f"{self.ref}{what} ({self.part} ±{_pct(self.tolerance)}) -> `{self.alternative}` "
            f"±{_pct(self.alt_tolerance)}"
        )


@dataclass
class WindowCheck:
    id: str
    limit_lo: float | None
    limit_hi: float | None
    lo: float  # worst-case range of the current design
    hi: float
    verdict: str  # ok | recenter | tighter_parts | infeasible | design (one-sided limit)
    spread: float = 0.0
    corner_spread: float = 0.0
    best_spread: float = 0.0
    shift: float | None = None  # recenter: move the nominal value by this much
    upgrades: list[Upgrade] = field(default_factory=list)
    relaxed_lo: float | None = None
    relaxed_hi: float | None = None

    @property
    def width(self) -> float:
        if self.limit_lo is None or self.limit_hi is None:
            return math.inf
        return self.limit_hi - self.limit_lo

    @property
    def centre_offset(self) -> float:
        """Window centre minus worst-case range centre (move the nominal value by this much)."""
        if self.limit_lo is None or self.limit_hi is None:
            return 0.0
        return (self.limit_lo + self.limit_hi) / 2 - (self.lo + self.hi) / 2

    @property
    def centred(self) -> bool:
        """Off-centre by at most 5 % of the spread: the relaxation is then (close to) the smallest."""
        return abs(self.centre_offset) <= 0.05 * self.spread

    @property
    def upgradable(self) -> bool:
        """Tighter parts would shrink the spread noticeably (worth one more design attempt)."""
        return bool(self.upgrades) and self.best_spread < 0.9 * self.spread

    def relative_change(self) -> float:
        """Largest move of a limit, relative to the window centre."""
        ref = max(abs(((self.limit_lo or 0) + (self.limit_hi or 0)) / 2), self.width, 1e-12)
        moves = [
            abs(new - old)
            for new, old in ((self.relaxed_lo, self.limit_lo), (self.relaxed_hi, self.limit_hi))
            if new is not None and old is not None
        ]
        return max(moves, default=0.0) / ref

    def explain(self) -> str:
        win = f"{_g(self.limit_lo)}..{_g(self.limit_hi)}"
        rng = f"{self.lo:.4g}..{self.hi:.4g}"
        if self.verdict == "recenter":
            return (
                f"{self.id}: the worst-case range {rng} is no wider than the window {win} but off-centre; "
                f"move the nominal value by {self.shift:+.4g}"
            )
        if self.verdict == "tighter_parts":
            return (
                f"{self.id}: the worst-case spread {self.spread:.4g} exceeds the window width "
                f"{self.width:.4g}; with tighter registered parts it would be about {self.best_spread:.4g}: "
                + "; ".join(u.text() for u in self.upgrades[:4])
            )
        if self.verdict == "infeasible":
            centre = (
                ""
                if self.centred
                else f" The design is off-centre: moving the nominal value by {self.centre_offset:+.4g} "
                "would make the necessary relaxation smaller."
            )
            parts = (
                " Tighter registered parts reduce it to about "
                f"{self.best_spread:.4g} ({'; '.join(u.text() for u in self.upgrades[:4])}), still too wide."
                if self.upgrades
                else " No registered part of the same kind has a tighter tolerance."
            )
            return (
                f"{self.id}: the window {win} (width {self.width:.4g}) is narrower than the worst-case "
                f"spread the parts' tolerances cause ({self.spread:.4g} for this design, of which "
                f"{self.corner_spread:.4g} from the supply range).{parts}{centre} Smallest window this "
                f"design passes: {_g(self.relaxed_lo)}..{_g(self.relaxed_hi)}"
            )
        return f"{self.id}: worst case {rng}, limit {win}"


@dataclass
class Feasibility:
    eligible: bool  # everything passes except G7 tolerance windows
    checks: list[WindowCheck] = field(default_factory=list)
    reason: str = ""

    @property
    def infeasible(self) -> list[WindowCheck]:
        return [c for c in self.checks if c.verdict == "infeasible"]

    @property
    def stop_now(self) -> bool:
        """Proven infeasible, no tighter part left to try and the design centred: further design
        attempts cannot make the necessary relaxation smaller."""
        return (
            self.eligible
            and bool(self.infeasible)
            and not any(c.upgradable or not c.centred for c in self.infeasible)
        )

    def changes(self) -> list[dict]:
        out = []
        for c in self.infeasible:
            for fld, old, new in (("min", c.limit_lo, c.relaxed_lo), ("max", c.limit_hi, c.relaxed_hi)):
                if old is not None and new is not None and new != old:
                    out.append({"criterion": c.id, "field": fld, "old": old, "new": new})
        return out

    def max_relative_change(self) -> float:
        return max((c.relative_change() for c in self.infeasible), default=0.0)

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "checks": [asdict(c) for c in self.checks],
            "changes": self.changes(),
            "max_relative_change": self.max_relative_change(),
        }

    def to_markdown(self) -> str:
        lines = []
        for c in self.checks:
            lines.append(f"- **{c.verdict}** — {c.explain()}")
        return "\n".join(lines)


def _pct(t: float) -> str:
    return f"{t * 100:.3g} %"


def _g(x: float | None) -> str:
    return "" if x is None else f"{x:.6g}"


def _round_out(lo: float, hi: float, centre: float, width: float) -> tuple[float, float]:
    step = 10 ** math.floor(math.log10(max(abs(centre), width, 1e-12) * 1e-3))
    digits = max(0, -math.floor(math.log10(step)))
    return (
        round(math.floor(lo / step + 1e-9) * step, digits),
        round(math.ceil(hi / step - 1e-9) * step, digits),
    )


def _vmax(pd: PartDef) -> float:
    return min((r.max for r in pd.ratings if r.type == "voltage"), default=math.inf)


def best_alternative(pd: PartDef, item: dict, db: PartsDB, spec: Spec) -> tuple[str, float] | None:
    """Tightest-tolerance registered part that could take this part's place (None: none tighter)."""
    tol = item["tolerance"]
    forbidden = set(spec.parts_policy.forbidden)
    best: tuple[str, float] | None = None
    if item["key"] == "value":
        try:
            value = parse_value(item["value"])
        except ValueError:
            return None
        group = _GROUPS.get(pd.kind, (pd.kind,))
        v_need = min(_vmax(pd), spec.power_input.v_max / spec.derating.voltage)
        for k in db.keys():
            cand = db[k]
            if k in forbidden or cand.kind not in group or cand.value != "required" or not cand.tolerance:
                continue
            if cand.value_min is not None and value < cand.value_min * (1 - 1e-9):
                continue
            if cand.value_max is not None and value > cand.value_max * (1 + 1e-9):
                continue
            if _vmax(cand) < v_need or (spec.parts_policy.tht_only and cand.mount != "tht"):
                continue
            if cand.tolerance < tol - 1e-12 and (best is None or cand.tolerance < best[1]):
                best = (k, cand.tolerance)
        return best
    name = item["key"]
    ref_prm = pd.spice.params.get(name) if pd.spice else None
    if ref_prm is None:
        return None
    for k in db.keys():
        cand = db[k]
        prm = cand.spice.params.get(name) if cand.kind == pd.kind and cand.spice else None
        if k in forbidden or prm is None or not prm.tolerance:
            continue
        if abs(prm.value - ref_prm.value) > 1e-6 * max(abs(ref_prm.value), 1.0):
            continue
        if prm.tolerance < tol - 1e-12 and (best is None or prm.tolerance < best[1]):
            best = (k, prm.tolerance)
    return best


def assess(report: VerificationReport, spec: Spec, db: PartsDB) -> Feasibility | None:
    """None when G7 did not run a worst-case analysis with sensitivities (nothing to assess)."""
    g7 = report.gate("G7")
    if g7 is None or g7.status != Status.FAIL or "sensitivity" not in g7.metrics:
        return None
    m = g7.metrics
    others_pass = all(g.status == Status.PASS for g in report.gates if g.gate != "G7")
    only_windows = all(f.rule == "tolerance.criterion" for f in g7.findings if f.severity == Severity.ERROR)
    measured = all("= n/a" not in f.message for f in g7.findings if f.severity == Severity.ERROR)
    reason = ""
    if not others_pass:
        reason = "other gates fail as well"
    elif not only_windows:
        reason = "G7 also reports part-rating violations"
    elif not measured:
        reason = "a criterion could not be measured in a tolerance corner"
    res = Feasibility(eligible=not reason, reason=reason)
    items = m.get("items", [])
    effects_all = m["sensitivity"].get("effects", {})
    alts: list[tuple[str, float] | None] = []
    for it in items:
        pd = db.get(it["part"])
        alts.append(best_alternative(pd, it, db, spec) if pd is not None else None)
    crit = {c.key(): c for c in spec.acceptance}
    for row in m.get("criteria", []):
        if row.get("passed") or row["id"] not in crit or "lo" not in row:
            continue
        c = crit[row["id"]]
        lim_lo, lim_hi = getattr(c, "min", None), getattr(c, "max", None)
        chk = WindowCheck(row["id"], lim_lo, lim_hi, row["lo"], row["hi"], "design")
        chk.spread = row["hi"] - row["lo"]
        corners = m.get("corners", {}).get(row["id"], [])
        chk.corner_spread = (max(corners) - min(corners)) if len(corners) > 1 else 0.0
        effects = effects_all.get(row["id"], [0.0] * len(items))
        total = sum(abs(e) for e in effects)
        reduced = 0.0
        ups: list[tuple[float, Upgrade]] = []
        for it, e, alt in zip(items, effects, alts, strict=False):
            reduced += abs(e) * (alt[1] / it["tolerance"] if alt else 1.0)
            if alt and abs(e) > 0.02 * total:
                ups.append((abs(e), Upgrade(it["ref"], it["key"], it["part"], it["tolerance"], *alt)))
        chk.upgrades = [u for _, u in sorted(ups, key=lambda x: -x[0])]
        r = reduced / total if total > 0 else 1.0
        chk.best_spread = chk.corner_spread + max(chk.spread - chk.corner_spread, 0.0) * r
        if lim_lo is None or lim_hi is None:
            res.checks.append(chk)  # one-sided: the design can always add margin
            continue
        if chk.spread <= chk.width:
            chk.verdict = "recenter"
            chk.shift = chk.centre_offset
        elif chk.best_spread <= chk.width:
            chk.verdict = "tighter_parts"
        else:
            chk.verdict = "infeasible"
            lo, hi = _round_out(row["lo"], row["hi"], (lim_lo + lim_hi) / 2, chk.width)
            chk.relaxed_lo, chk.relaxed_hi = min(lim_lo, lo), max(lim_hi, hi)
        res.checks.append(chk)
    return res
