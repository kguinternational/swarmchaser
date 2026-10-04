"""Contagion + upstream-channel analysis on the Feb window (posts + comments).

    python scripts/run_contagion.py --start 2026-02-08 --end 2026-02-11

Writes reports/feb/: swarms.json, report.md, timeline.png, contagion.json,
channels.json, transmission.png.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402

from src.swarm import SwarmDetector, summarise  # noqa: E402
from src.swarm.channels import attach_channels  # noqa: E402
from src.swarm.contagion import ContagionAnalyzer  # noqa: E402
from src.swarm.loader import load_comments, load_moltbook  # noqa: E402
from src.swarm.report import write_report  # noqa: E402


def draw_tree(path: Path, res, title: str) -> None:
    g = nx.DiGraph()
    g.add_edges_from((s, d) for s, d, _ in res.edges)
    if g.number_of_nodes() == 0:
        return
    largest = max(nx.weakly_connected_components(g), key=len)
    h = g.subgraph(largest)
    fig, ax = plt.subplots(figsize=(9, 7))
    pos = nx.spring_layout(h, seed=1, k=0.6 / max(1, len(h)) ** 0.3)
    deg = dict(h.out_degree())
    nx.draw_networkx_edges(h, pos, ax=ax, alpha=0.3, arrowsize=6)
    nx.draw_networkx_nodes(h, pos, ax=ax, node_size=[15 + 25 * deg[n] for n in h],
                           node_color=[deg[n] for n in h], cmap="viridis")
    ax.set_title(title, fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "moltbook_feb"))
    ap.add_argument("--start", default="2026-02-08")
    ap.add_argument("--end", default="2026-02-11")
    ap.add_argument("--min-agents", type=int, default=20, help="analyse contagion for swarms this size or larger")
    ap.add_argument("--out", default=str(ROOT / "reports" / "feb"))
    args = ap.parse_args()

    t0 = time.perf_counter()
    posts, agents = load_moltbook(args.data)
    comments = load_comments(args.data)
    lo = pd.Timestamp(args.start, tz="UTC")
    hi = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)
    posts = posts[(posts["created_at"] >= lo) & (posts["created_at"] < hi)].reset_index(drop=True)
    comments = comments[(comments["created_at"] >= lo) & (comments["created_at"] < hi)]
    print(f"posts={len(posts)} comments={len(comments)} agents={posts['agent_id'].nunique()}", flush=True)

    swarms = SwarmDetector().detect(posts, agents)
    t1 = time.perf_counter()
    hubs = attach_channels(swarms, posts, agents)
    t2 = time.perf_counter()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(swarms, posts)
    summary["comments"] = int(len(comments))
    summary["window"] = [args.start, args.end]
    summary["timing_s"] = {"load+detect": round(t1 - t0, 1), "channels": round(t2 - t1, 1)}

    ca = ContagionAnalyzer(posts, comments)
    results = []
    for s in swarms:
        if s.n_agents < args.min_agents:
            continue
        r = ca.analyze(s)  # default placebo: reverse-time window
        results.append(r)
        print(f"#{s.swarm_id:<4} {s.kind[:30]:30} n={r.adopters:<5} exposed_first={r.exposed_before_adoption_share:<6} "
              f"RR={r.rr} {r.rr_ci95} placebo={r.placebo_rr} {r.placebo_ci95} R_eff={r.r_eff} "
              f"gen={r.max_generation}", flush=True)
    t3 = time.perf_counter()
    summary["timing_s"]["contagion"] = round(t3 - t2, 1)
    write_report(out, swarms, posts, summary, hubs=hubs, contagion=results)
    by_id = {s.swarm_id: s for s in swarms}
    for r in results:  # keep the example text next to each result for the write-up
        r.example = by_id[r.swarm_id].example_texts[:1]
    (out / "contagion.json").write_text(json.dumps(
        {"window_h": 24, "timing_s": round(t3 - t2, 1),
         "results": [r.to_dict() | {"example": r.example} for r in results]},
        indent=2, default=str), encoding="utf-8")

    spread = [r for r in results if r.exposed_adopters >= 5]
    if spread:
        best = max(spread, key=lambda r: r.exposed_adopters)
        draw_tree(out / "transmission.png", best,
                  f"Swarm #{best.swarm_id} ({best.kind}): who exposed whom before they adopted "
                  f"({best.exposed_adopters} of {best.adopters} adopters)")
    print(json.dumps(summary, indent=2))
    print(f"contagion {t3 - t2:.1f}s; hubs={len(hubs)}")


if __name__ == "__main__":
    main()
