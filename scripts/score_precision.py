"""Score precision of the current run against eval/labels_top40.csv.

    python scripts/score_precision.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    labels = list(csv.DictReader(open(ROOT / "eval" / "labels_top40.csv", encoding="utf-8")))
    swarms = json.load(open(ROOT / "reports" / "swarms.json", encoding="utf-8"))["swarms"]
    by_prefix: dict[str, list] = {}
    for s in swarms:
        if s["example_texts"]:
            by_prefix.setdefault(s["example_texts"][0][:40], []).append(s)

    matched = []
    for row in labels:
        cands = by_prefix.get(row["template_prefix"][:40], [])
        if cands:
            matched.append((row, cands.pop(0)))
    c = Counter(r["label"] for r, _ in matched)
    decided = c["coordinated"] + c["benign"]

    def prec(rows):
        k = Counter(r["label"] for r in rows)
        d = k["coordinated"] + k["benign"]
        return k["coordinated"] / d if d else None

    top10 = [r for r, s in matched if s["swarm_id"] < 10]
    out = {
        "labelled": len(labels), "matched_in_current_run": len(matched), "counts": dict(c),
        "precision_all": round(c["coordinated"] / len(matched), 3) if matched else None,
        "precision_excluding_unclear": round(c["coordinated"] / decided, 3) if decided else None,
        "precision_top10_excluding_unclear": round(prec(top10), 3) if top10 and prec(top10) is not None else None,
        "benign_kinds": Counter(r["note"] for r, _ in matched if r["label"] == "benign").most_common(),
    }
    (ROOT / "reports" / "precision.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
