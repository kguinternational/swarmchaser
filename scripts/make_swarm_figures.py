"""Figures for the write-up from reports/*.json.

    python scripts/make_swarm_figures.py
Writes reports/early_warning.png and reports/contagion.png
(from reports/early_warning.json and reports/feb/contagion.json).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

R = Path(__file__).resolve().parent.parent / "reports"


def early_warning() -> None:
    d = json.loads((R / "early_warning.json").read_text(encoding="utf-8"))
    ws = sorted([w for w in d["swarms"] if w["flagged_at"]], key=lambda w: -w["final_posts"])[:15]
    labels = [f"#{w['swarm_id']} {w['kind'].split(' (')[0]} ({w['final_agents']} agents)" for w in ws]
    before = [w["final_posts"] * (1 - w["preventable_post_share"]) for w in ws]
    after = [w["final_posts"] * w["preventable_post_share"] for w in ws]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    y = range(len(ws))
    ax.barh(y, before, color="#888", label="posts before first flag")
    ax.barh(y, after, left=before, color="#d62728", label="posts after first flag (preventable)")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xscale("symlog", linthresh=10)
    ax.set_xlabel("swarm posts (symlog)")
    s = d["summary"]
    ax.set_title(f"Replay at 6 h checkpoints: {s['posts_after_flag']:,} of {s['posts_total']:,} swarm posts "
                 f"came after the first flag", fontsize=10)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(R / "early_warning.png", dpi=150)
    plt.close(fig)


def contagion() -> None:
    p = R / "feb" / "contagion.json"
    if not p.exists():
        return
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = [r for r in d["results"] if r["rr"] is not None]
    if not rows:
        return
    from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

    fig, ax = plt.subplots(figsize=(9, 2.6 + 0.9 * len(rows)))
    for i, r in enumerate(rows):
        lo, hi = r["rr_ci95"]
        ax.errorbar(r["rr"], i - 0.12, xerr=[[r["rr"] - lo], [hi - r["rr"]]], fmt="o", color="#1f77b4",
                    capsize=4, label=f"after exposure: adoption within {d['window_h']} h" if i == 0 else None)
        if r["placebo_rr"] is not None:
            plo, phi = r["placebo_ci95"]
            ax.errorbar(r["placebo_rr"], i + 0.12, xerr=[[r["placebo_rr"] - plo], [phi - r["placebo_rr"]]],
                        fmt="x", color="#d62728", capsize=4,
                        label=f"placebo: adoption in the {d['window_h']} h before exposure" if i == 0 else None)
    ax.axvline(1, color="k", lw=0.8, ls="--")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"#{r['swarm_id']} " + (r["example"][0] if r["example"] else "")[:40] + "..."
                        for r in rows], fontsize=8)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator([0.5, 1, 2, 3, 5, 8, 13, 20]))
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("relative risk vs time-matched commenters (95% CI)")
    ax.set_title("Exposure -> adoption, Moltbook 8-11 Feb 2026", fontsize=10)
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=1, frameon=False)
    fig.tight_layout()
    fig.savefig(R / "contagion.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    early_warning()
    contagion()
