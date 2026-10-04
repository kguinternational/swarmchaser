"""Recall check: plant swarms of known shape into the real Moltbook slice.

    python scripts/evaluate_planted.py
Writes reports/planted_eval.json and prints a table.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.swarm import SwarmDetector, load_moltbook  # noqa: E402
from src.swarm.planted import plant, score_recovery  # noqa: E402


def main() -> None:
    posts, agents = load_moltbook(ROOT / "data" / "moltbook")
    posts, agents, truth = plant(posts, agents)
    swarms = SwarmDetector().detect(posts, agents)
    res = score_recovery(swarms, truth)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "planted_eval.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"{'planted':24} {'size':>4} {'expect':>6} {'recall':>6} {'purity':>6} {'rank':>5} {'score':>5}  kind / attribution")
    for r in res:
        print(f"{r['planted']:24} {r['size']:>4} {str(r['expected_detectable']):>6} {r['recall']:>6} "
              f"{r['purity']:>6} {str(r['rank']):>5} {str(r['score']):>5}  {r['detected_as']} / {r['attribution']}")


if __name__ == "__main__":
    main()
