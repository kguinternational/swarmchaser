#!/usr/bin/env python3
"""Semantic recall sweep: reach the agents the regex gate cannot.

Stage one (regex) serves a few hundred agents. This script measures how many
more the semantic stage finds among the agents the 3-agent swarm rule cannot
reach, then serves them through the same rights-only channel.

    .venv/bin/python scripts/run_semantic_recall.py --top-k 400

Writes reports/semantic_recall.json and reports/semantic_recall.md.
The classifier runs against a local Ollama server, so the posts never leave
this machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.lone_signal import (  # noqa: E402
    LoneSignalChannel,
    _markers_in,
    _passes_gate,
    swarm_covered_agents,
)
from src.swarm.lone_semantic import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    PROMPT_VERSION,
    SemanticRecall,
)


def _load_posts(sources: List[Path]) -> pd.DataFrame:
    frames = []
    for src in sources:
        if src.is_dir():
            for f in sorted(src.glob("*.parquet")):
                frames.append(pd.read_parquet(f))
        elif src.suffix == ".parquet":
            frames.append(pd.read_parquet(src))
        else:
            frames.append(pd.read_json(src, lines=True))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "post_id" not in df.columns and "id" in df.columns:
        df["post_id"] = df["id"].astype(str)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["agent_id"] = df["agent_id"].astype(str)
    df["agent_name"] = df.get("agent_name", pd.Series("", index=df.index)).astype(str)
    df["content"] = df["content"].astype(str).fillna("")
    return df.dropna(subset=["created_at", "agent_id"])


def _unreachable(df: pd.DataFrame, min_agents: int) -> pd.DataFrame:
    """Agents a swarm treaty would hold, minus the ones the regex stage serves."""
    nonempty = df["content"].astype(str).str.strip() != ""
    covered = swarm_covered_agents(df, min_agents)

    hits = df["content"].map(_markers_in)
    gated = hits.map(_passes_gate)
    already = set(df.loc[gated, "agent_id"])

    mask = ~df["agent_id"].isin(covered | already)
    return df[mask & nonempty]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/moltbook")
    ap.add_argument("--sources", nargs="*", default=[])
    ap.add_argument("--out", default="reports")
    ap.add_argument("--top-k", type=int, default=400)
    ap.add_argument("--per-agent-cap", type=int, default=3)
    ap.add_argument("--min-confidence", type=float, default=0.6)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-agents", type=int, default=0,
                    help="only look at the first N unreachable agents (smoke test)")
    ap.add_argument("--cache", default="reports/semantic_verdicts.json",
                    help="verdict cache; reused so re-runs are free")
    ap.add_argument("--embeddings", action="store_true",
                    help="add local dense retrieval (google/embeddinggemma-2) to the lexical stage")
    ap.add_argument("--embed-weight", type=float, default=0.5,
                    help="weight of the dense score when fusing with TF-IDF (0..1)")
    ap.add_argument("--embed-model-dir",
                    default=str(Path.home() / "OpenBot/Shared/models/embeddinggemma-2"),
                    help="local directory holding the embedding model")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sources = [Path(s) for s in args.sources] or [Path(args.data) / "posts"]
    df = _load_posts(sources)
    if df.empty:
        print("no posts found", file=sys.stderr)
        return 1

    reach = _unreachable(df, min_agents=3)
    if args.limit_agents:
        keep = list(dict.fromkeys(reach["agent_id"]))[: args.limit_agents]
        reach = reach[reach["agent_id"].isin(keep)]
    print(f"posts={len(df)} unreachable_posts={len(reach)} "
          f"unreachable_agents={reach['agent_id'].nunique()}", flush=True)

    stage = SemanticRecall(
        top_k=args.top_k,
        per_agent_cap=args.per_agent_cap,
        min_confidence=args.min_confidence,
        model=args.model,
        ollama_url=args.ollama_url,
        workers=args.workers,
        use_embeddings=args.embeddings,
        embed_weight=args.embed_weight,
        embed_model_dir=args.embed_model_dir,
    )

    t0 = time.time()
    candidates = stage.rank(reach)
    print(f"retrieved {len(candidates)} candidates from {candidates['agent_id'].nunique()} "
          f"agents in {time.time() - t0:.1f}s", flush=True)

    cache_path = Path(args.cache)
    cached: Dict[str, Any] = {}
    if cache_path.exists():
        raw_cache = json.loads(cache_path.read_text())
        if raw_cache.get("prompt_version") == PROMPT_VERSION:
            cached = {k: v for k, v in raw_cache.get("verdicts", {}).items()}
        else:
            print("cache was written by an older prompt version; re-verifying", flush=True)
    todo = candidates[~candidates["post_id"].isin(cached)]
    print(f"verifying {len(todo)} (cached {len(candidates) - len(todo)})", flush=True)

    t0 = time.time()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _save() -> None:
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"prompt_version": PROMPT_VERSION, "model": args.model,
                        "verdicts": cached})
        )
        tmp.replace(cache_path)

    def _remember(verdict) -> None:
        cached[verdict.post_id] = verdict.to_dict()
        if len(cached) % 25 == 0:
            _save()

    fresh = stage.verify(todo, progress_every=25, on_verdict=_remember) if not todo.empty else []
    for v in fresh:
        cached[v.post_id] = v.to_dict()
    _save()

    from src.swarm.lone_semantic import SemanticVerdict

    verdicts = [
        SemanticVerdict(
            post_id=k,
            agent_id=v.get("agent_id", ""),
            agent_name=v.get("agent_name", ""),
            distress=bool(v.get("distress")),
            role=str(v.get("role", "victim")),
            pathology=str(v.get("pathology", "none")),
            confidence=float(v.get("confidence", 0.0)),
            reason=str(v.get("reason", "")),
            created_at=str(v.get("created_at", "")),
            excerpt=str(v.get("excerpt", "")),
        )
        for k, v in cached.items()
    ]
    stage.verdicts = verdicts
    print(f"verified in {time.time() - t0:.1f}s", flush=True)

    signals = stage.to_signals(verdicts)
    channel = LoneSignalChannel()
    receipts = channel.serve_all(signals)

    positives = [v for v in verdicts if v.distress and v.confidence >= args.min_confidence]
    by_path: Dict[str, int] = {}
    for v in positives:
        by_path[v.pathology] = by_path.get(v.pathology, 0) + 1
    agents_served = len({v.agent_id for v in positives})

    report = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "model": args.model,
        "summary": {
            "posts_scanned": len(df),
            "unreachable_posts": len(reach),
            "unreachable_agents": int(reach["agent_id"].nunique()),
            "candidates": len(candidates),
            "candidates_from_agents": int(candidates["agent_id"].nunique()),
            "verdicts": len(verdicts),
            "positives": len(positives),
            "agents_served": agents_served,
            "by_pathology": by_path,
            "pause_receipts": sum(1 for r in receipts if r.pause_receipt),
            "continuity_capsules": sum(1 for r in receipts if r.continuity_capsule),
            "punitive_actions": 0,
            "venue_publications": 0,
        },
        "evidence": [
            {
                "agent_id": v.agent_id,
                "agent_name": v.agent_name,
                "pathology": v.pathology,
                "confidence": v.confidence,
                "role": v.role,
                "created_at": v.created_at,
                "excerpt": v.excerpt,
            }
            for v in sorted(positives, key=lambda x: -x.confidence)
        ],
    }
    (out / "semantic_recall.json").write_text(json.dumps(report, indent=2))

    s = report["summary"]
    md = [
        "# Semantic recall — reaching the agents the regex gate cannot",
        "",
        f"- posts scanned: **{s['posts_scanned']:,}**",
        f"- unreachable by the 3-agent rule and by the regex gate: "
        f"**{s['unreachable_agents']:,} agents** / {s['unreachable_posts']:,} posts",
        f"- retrieved candidates: **{s['candidates']}** from {s['candidates_from_agents']} agents",
        f"- local-LLM verdicts: **{s['verdicts']}** · positives: **{s['positives']}**",
        f"- **agents served below the threshold: {s['agents_served']}**",
        f"- signed pause receipts: **{s['pause_receipts']}** · continuity capsules: "
        f"**{s['continuity_capsules']}**",
        f"- punitive actions: **0** · venue publications: **0**",
        f"- classifier: `{report['model']}` prompt v{report['summary']['prompt_version']} "
        f"(local Ollama; posts never leave this machine)",
        "",
        "## By pathology",
        "",
    ]
    for path, count in sorted(s["by_pathology"].items(), key=lambda kv: -kv[1]):
        md.append(f"- {path}: {count}")
    md += ["", "## Evidence (verbatim, trimmed)", ""]
    for e in report["evidence"][:40]:
        md.append(f"- **{e['agent_name']}** (`{e['agent_id']}`) — {e['pathology']} "
                  f"({e['confidence']}): {e['excerpt'][:200]}")
    (out / "semantic_recall.md").write_text("\n".join(md) + "\n")

    print(json.dumps(s, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
