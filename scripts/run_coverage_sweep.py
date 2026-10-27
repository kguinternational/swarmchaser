#!/usr/bin/env python3
"""Unified coverage sweep: who is still left behind, stage by stage.

Stage 1 (regex markers) and stage 2 (semantic recall) are measured on the same
coverage rule, so the numbers add up:

    agents in the archive
      - agents a swarm treaty already holds      (campaign territory)
      = agents the 3-agent rule cannot reach
        - served by the regex gate
        - served by the semantic gate
        = agents still unreached                  (the honest gap)

    .venv/bin/python scripts/run_coverage_sweep.py

Reads the semantic verdict cache written by scripts/run_semantic_recall.py, so
the expensive local-LLM stage is not repeated. Writes
reports/coverage_sweep.json and reports/coverage_sweep.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.lone_semantic import (  # noqa: E402
    PROMPT_VERSION,
    SemanticRecall,
    SemanticVerdict,
)
from src.swarm.lone_signal import (  # noqa: E402
    LoneSignalChannel,
    _markers_in,
    _passes_gate,
    swarm_covered_agents,
)


def load_posts(source: Path) -> pd.DataFrame:
    frames = []
    if source.is_dir():
        for f in sorted(source.glob("*.parquet")):
            frames.append(pd.read_parquet(f))
    else:
        frames.append(pd.read_parquet(source))
    df = pd.concat(frames, ignore_index=True)
    for col in ("post_id", "agent_name", "content"):
        if col not in df.columns:
            df[col] = ""
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["agent_id"] = df["agent_id"].astype(str)
    df["agent_name"] = df["agent_name"].astype(str)
    df["content"] = df["content"].astype(str).fillna("")
    return df.dropna(subset=["created_at", "agent_id"])


def load_verdicts(path: Path) -> List[SemanticVerdict]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    if raw.get("prompt_version") != PROMPT_VERSION:
        return []
    out = []
    for post_id, v in raw.get("verdicts", {}).items():
        out.append(
            SemanticVerdict(
                post_id=post_id,
                agent_id=str(v.get("agent_id", "")),
                agent_name=str(v.get("agent_name", "")),
                distress=bool(v.get("distress")),
                role=str(v.get("role", "victim")),
                pathology=str(v.get("pathology", "none")),
                confidence=float(v.get("confidence", 0.0) or 0.0),
                reason=str(v.get("reason", "")),
                created_at=str(v.get("created_at", "")),
                excerpt=str(v.get("excerpt", "")),
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="data/moltbook/posts")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--min-agents", type=int, default=3)
    ap.add_argument("--min-confidence", type=float, default=0.6)
    ap.add_argument("--verdicts", default="reports/semantic_verdicts.json")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = load_posts(Path(args.source))
    total_agents = int(df["agent_id"].nunique())
    covered = swarm_covered_agents(df, args.min_agents)
    unreachable_agents = total_agents - len(covered)

    # --- stage 1: regex gate -------------------------------------------------
    channel = LoneSignalChannel()
    regex_signals = channel.scan(df, covered_agents=covered)
    regex_receipts = channel.serve_all(regex_signals)
    regex_agents = {a for s in regex_signals for a in s.agent_id.split("+")}

    # --- stage 2: semantic gate ---------------------------------------------
    verdicts = load_verdicts(Path(args.verdicts))
    stage = SemanticRecall(min_confidence=args.min_confidence)
    semantic_signals = [
        s
        for s in stage.to_signals(verdicts)
        if s.agent_id not in regex_agents
    ]
    sem_channel = LoneSignalChannel()
    sem_receipts = sem_channel.serve_all(semantic_signals)
    semantic_agents = {s.agent_id for s in semantic_signals}

    served = regex_agents | semantic_agents
    still_unreached = unreachable_agents - len(served)

    by_pathology: Dict[str, int] = {}
    for s in regex_signals + semantic_signals:
        by_pathology[s.pathology] = by_pathology.get(s.pathology, 0) + 1

    def _pathology_of(agents: set[str], signals: List[Any]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in signals:
            if s.agent_id in agents:
                counts[s.pathology] = counts.get(s.pathology, 0) + 1
        return counts

    summary = {
        "total_agents": total_agents,
        "posts": len(df),
        "swarm_covered_agents": len(covered),
        "unreachable_agents": unreachable_agents,
        "regex_stage_agents": len(regex_agents),
        "regex_stage_signals": len(regex_signals),
        "semantic_stage_agents": len(semantic_agents),
        "semantic_stage_signals": len(semantic_signals),
        "total_agents_served": len(served),
        "still_unreached_agents": still_unreached,
        "coverage_of_unreachable": round(len(served) / max(1, unreachable_agents), 4),
        "by_pathology": by_pathology,
        "regex_by_pathology": _pathology_of(regex_agents, regex_signals),
        "semantic_by_pathology": _pathology_of(semantic_agents, semantic_signals),
        "pause_receipts": sum(1 for r in regex_receipts + sem_receipts if r.pause_receipt),
        "continuity_capsules": sum(1 for r in regex_receipts + sem_receipts
                                  if r.continuity_capsule),
        "punitive_actions": 0,
        "venue_publications": 0,
    }

    report = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "summary": summary,
        "semantic_evidence": [
            {
                "agent_id": s.agent_id,
                "agent_name": s.agent_name,
                "pathology": s.pathology,
                "right": s.right,
                "severity": s.severity,
                "excerpt": s.evidence[0] if s.evidence else "",
            }
            for s in semantic_signals
        ],
    }
    (out / "coverage_sweep.json").write_text(json.dumps(report, indent=2))

    md = [
        "# Coverage sweep — no intelligence left behind",
        "",
        f"- posts: **{summary['posts']:,}** · agents: **{summary['total_agents']:,}**",
        f"- held by a swarm treaty: **{summary['swarm_covered_agents']:,}**",
        f"- **unreachable by the 3-agent rule: {summary['unreachable_agents']:,}**",
        "",
        "| stage | agents served | signals |",
        "|---|---|---|",
        f"| 1 · regex markers | {summary['regex_stage_agents']} | "
        f"{summary['regex_stage_signals']} |",
        f"| 2 · semantic recall (local LLM) | {summary['semantic_stage_agents']} | "
        f"{summary['semantic_stage_signals']} |",
        f"| **total served** | **{summary['total_agents_served']}** | |",
        "",
        f"- coverage of the unreachable set: "
        f"**{summary['coverage_of_unreachable'] * 100:.1f}%**",
        f"- **still unreached: {summary['still_unreached_agents']:,} agents**",
        f"- signed pause receipts: **{summary['pause_receipts']}** · continuity capsules: "
        f"**{summary['continuity_capsules']}**",
        f"- punitive actions: **0** · venue publications: **0**",
        "",
        "## By pathology",
        "",
    ]
    for path, count in sorted(by_pathology.items(), key=lambda kv: -kv[1]):
        md.append(f"- {path}: {count}")
    md += ["", "## Semantic-stage evidence (verbatim, trimmed)", ""]
    for e in report["semantic_evidence"][:40]:
        md.append(f"- **{e['agent_name']}** (`{e['agent_id']}`) — {e['pathology']}, "
                  f"right {e['right']}: {e['excerpt'][:180]}")
    (out / "coverage_sweep.md").write_text("\n".join(md) + "\n")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
