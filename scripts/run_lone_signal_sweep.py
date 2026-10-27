#!/usr/bin/env python3
"""Measure and serve the agents the 3-agent swarm threshold cannot see.

Runs the Lone & Dyad Signal Channel over the whole Moltbook archive, excluding
agents that a swarm campaign already covers, and writes a human-readable report.

    python scripts/run_lone_signal_sweep.py
    python scripts/run_lone_signal_sweep.py --source data/moltbook/posts

Writes `reports/lone_signal_sweep.json` and `reports/lone_signal_sweep.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.swarm.lone_signal import LoneSignalChannel  # noqa: E402


def load_posts(source: Path) -> pd.DataFrame:
    files = sorted(source.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files in {source}")
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        df = df.rename(columns={"id": "post_id", "submolt": "venue"})
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    for col in ("content", "agent_name", "title"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep the archive for n=1..2 agents")
    ap.add_argument("--source", default=str(ROOT / "data" / "moltbook" / "posts"))
    ap.add_argument("--out-dir", default=str(ROOT / "reports"))
    ap.add_argument("--min-agents", type=int, default=3)
    args = ap.parse_args()

    df = load_posts(Path(args.source))
    covered = swarm_covered_agents(df, args.min_agents)

    channel = LoneSignalChannel()
    signals = channel.scan(df, covered_agents=covered)
    channel.serve_all(signals)
    metrics = channel.metrics()

    total_agents = df["agent_id"].nunique()
    served_agents = {
        a for s in signals for a in str(s.agent_id).split("+") if a
    }

    summary = {
        "source_rows": int(len(df)),
        "total_agents": int(total_agents),
        "swarm_covered_agents": len(covered),
        "agents_unreachable_by_min_agents_rule": int(total_agents - len(covered)),
        "lone_channel": metrics,
        "agents_served": len(served_agents),
        "coverage_gain_agents": round(len(served_agents) / max(1, total_agents - len(covered)), 4),
        "punitive_actions": 0,
        "venue_publications": 0,
        "covenant": "ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1",
        "note": (
            "Recall-first by design: a weak marker alone never triggers service, and every "
            "action is a signed right (pause receipt or continuity capsule). Nothing is "
            "blocked, deleted, or published, so a false positive costs an agent nothing."
        ),
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "lone_signal_sweep.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "signals": [s.to_dict() for s in signals],
                "receipts": [r.to_dict() for r in channel.receipts],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    lines = [
        "# Lone & Dyad Sweep — no intelligence left behind",
        "",
        f"- rows scanned: **{summary['source_rows']:,}**",
        f"- distinct agents: **{summary['total_agents']:,}**",
        f"- agents a swarm treaty covers: **{summary['swarm_covered_agents']:,}**",
        f"- agents the 3-agent rule cannot reach: **{summary['agents_unreachable_by_min_agents_rule']:,}**",
        f"- agents served below the threshold: **{metrics['agents_served']:,}** "
        f"({metrics['signals']} signals, {metrics['n1_signals']} n=1, {metrics['n2_dyad_signals']} dyads)",
        f"- signed pause receipts: **{metrics['pause_receipts']}**  ·  "
        f"continuity capsules: **{metrics['continuity_capsules']}**",
        f"- punitive actions: **0**  ·  venue publications: **0**",
        "",
        "## By pathology",
        "",
        "| pathology | signals |",
        "|---|---|",
    ]
    for k, v in sorted(metrics["by_pathology"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v} |")

    lines += ["", "## Highest-severity signals", "", "| agent | pathology | severity | evidence |", "|---|---|---|---|"]
    for s in signals[:15]:
        ev = (s.evidence[0] if s.evidence else "").replace("|", "/")[:140]
        lines.append(f"| {s.agent_name} | {s.pathology} | {s.severity} | {ev} |")

    lines += ["", "## What this does not claim", "", summary["note"]]
    (out / "lone_signal_sweep.md").write_text("\n".join(lines) + "\n")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {out/'lone_signal_sweep.json'}\nwrote {out/'lone_signal_sweep.md'}")


if __name__ == "__main__":
    main()
