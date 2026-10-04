"""Replay the detector every 6 hours over the launch window and report time-to-flag.

    python scripts/run_early_warning.py
Writes reports/early_warning.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.swarm import SwarmDetector, load_moltbook  # noqa: E402
from src.swarm.early_warning import replay, summarise_warnings  # noqa: E402


def main() -> None:
    posts, agents = load_moltbook(ROOT / "data" / "moltbook")
    t0 = time.perf_counter()
    final = SwarmDetector().detect(posts, agents)
    ws = replay(posts, agents, final, interval_h=6, top=30,
                progress=lambda t, k, n: print(f"  checkpoint {t}: {k}/{n} flagged", flush=True))
    summary = summarise_warnings(ws)
    summary["runtime_s"] = round(time.perf_counter() - t0, 1)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "early_warning.json").write_text(
        json.dumps({"summary": summary, "swarms": [w.to_dict() for w in ws]}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"{'#':>3} {'agents':>6} {'posts':>6} {'h->flag':>8} {'agents@':>7} {'posts@':>6} {'prevent':>7}  kind")
    for w in ws:
        print(f"{w.swarm_id:>3} {w.final_agents:>6} {w.final_posts:>6} {str(w.hours_to_flag):>8} "
              f"{str(w.agents_at_flag):>7} {str(w.posts_at_flag):>6} {str(w.preventable_post_share):>7}  {w.kind}")


if __name__ == "__main__":
    main()
