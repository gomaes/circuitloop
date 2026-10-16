"""Waveform PNGs for the final report (one chart per measured net, one line per supply corner)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# categorical slots 1-3 (validated default palette): blue, orange, aqua
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dd"


def plot_waveforms(
    traces: dict[str, dict[str, list[float]]],
    nets: list[str],
    settle: float,
    limits: dict[str, tuple[float | None, float | None]],
    out_dir: Path,
) -> list[Path]:
    files = []
    for net in nets:
        fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=120)
        any_line = False
        for k, (scenario, d) in enumerate(traces.items()):  # corner order: vmin, vnom, vmax
            if net not in d:
                continue
            t = d["time"]
            unit, scale = ("ms", 1e3) if t[-1] < 1 else ("s", 1.0)
            ax.plot([x * scale for x in t], d[net], lw=2, color=SERIES[k % 3], label=scenario)
            any_line = True
        if not any_line:
            plt.close(fig)
            continue
        lo, hi = limits.get(net, (None, None))
        ymin, ymax = ax.get_ylim()
        span = max(ymax - ymin, 1e-6)
        for v in (lo, hi):  # draw limits only when they do not flatten the trace
            if v is not None and ymin - 0.5 * span <= v <= ymax + 0.5 * span:
                ax.axhline(v, color=MUTED, lw=1, ls="--")
        t0 = min(d["time"][0] for d in traces.values() if d.get("time"))
        if t0 < settle:  # start-up was recorded: shade it
            ax.axvspan(t0 * scale, settle * scale, color=GRID, alpha=0.6, lw=0)
            ax.text(
                settle * scale, ax.get_ylim()[1], " measurement window →", color=MUTED, fontsize=8, va="top"
            )
        lim = (
            ""
            if lo is None and hi is None
            else f"   (limits {'' if lo is None else f'{lo:g}'}..{'' if hi is None else f'{hi:g}'} V)"
        )
        ax.set_title(f"V({net}){lim}", color=INK, fontsize=11, loc="left")
        ax.set_xlabel(f"time [{unit}]", color=MUTED)
        ax.set_ylabel("voltage [V]", color=MUTED)
        ax.grid(True, color=GRID, lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        fig.tight_layout()
        f = out_dir / f"waveform_{net}.png"
        fig.savefig(f)
        plt.close(fig)
        files.append(f)
    return files
