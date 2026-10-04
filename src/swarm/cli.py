"""Run swarm detection over a Moltbook slice and write a report.

    python -m src.swarm.cli --data data/moltbook --out reports

Contagion needs comments and lives in scripts/run_contagion.py.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .channels import attach_channels
from .detector import DetectorConfig, SwarmDetector, summarise
from .loader import load_moltbook
from .report import write_report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Swarmchaser: detect coordinated agent swarms")
    ap.add_argument("--data", default="data/moltbook")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--min-agents", type=int, default=3)
    ap.add_argument("--no-near", action="store_true", help="disable MinHash near-duplicate keys")
    ap.add_argument("--no-operator", action="store_true", help="disable shared-operator links")
    ap.add_argument("--baseline-trials", type=int, default=20)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    posts, agents = load_moltbook(args.data)
    t1 = time.perf_counter()
    cfg = DetectorConfig(min_agents=args.min_agents, use_near_duplicates=not args.no_near,
                         use_operator_links=not args.no_operator, baseline_trials=args.baseline_trials)
    swarms = SwarmDetector(cfg).detect(posts, agents)
    t2 = time.perf_counter()
    hubs = attach_channels(swarms, posts, agents)
    t3 = time.perf_counter()

    summary = summarise(swarms, posts)
    summary["window"] = [str(posts["created_at"].min()), str(posts["created_at"].max())]
    summary["swarms_with_upstream_channel"] = sum(1 for s in swarms if s.channels)
    summary["timing_s"] = {"load": round(t1 - t0, 2), "detect": round(t2 - t1, 2),
                           "channels": round(t3 - t2, 2)}

    out = Path(args.out)
    write_report(out, swarms, posts, summary, top=args.top, hubs=hubs)
    print(json.dumps(summary, indent=2))
    for s in swarms[: args.top]:
        ch = ", ".join(c["channel"] for c in s.channels[:2])
        print(f"#{s.swarm_id:<3} score={s.score:.2f} agents={s.n_agents:<5} posts={s.n_posts:<6} "
              f"{s.kind} | channels: {ch or '-'} :: {s.example_texts[:1]}")


if __name__ == "__main__":
    main()
