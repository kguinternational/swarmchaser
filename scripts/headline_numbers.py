"""Collect the headline numbers quoted in README.md / SUBMISSION.md from report files.

    python scripts/headline_numbers.py
Reads reports/*.json and reports/feb/*.json, writes reports/headline.json.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "reports"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    sw = load(R / "swarms.json")
    swarms = sw["swarms"]
    out: dict = {"launch_window": sw["summary"]}

    big = max(swarms, key=lambda s: s["n_agents"])
    out["largest"] = {k: big[k] for k in ("swarm_id", "kind", "n_agents", "n_posts", "span_hours",
                                          "operators_known", "distinct_operators", "top_operator_share",
                                          "registration_burst_share")}
    multi = [s for s in swarms if s["operators_known"] >= 3]
    out["operator"] = {
        "swarms_with_3plus_known": len(multi),
        "of_which_top_operator_ge_half": sum(s["top_operator_share"] >= 0.5 for s in multi),
        "coverage_known_owner": round(sum(s["operators_known"] for s in swarms)
                                      / max(1, sum(s["n_agents"] for s in swarms)), 3),
    }
    inj = [s for s in swarms if s["kind"].startswith("agent-recruitment")]
    out["injection"] = {"swarms": len(inj), "agents": sum(s["n_agents"] for s in inj),
                        "posts": sum(s["n_posts"] for s in inj)}
    out["channels"] = {
        "swarms_with_channel": sum(bool(s["channels"]) for s in swarms),
        "top50_with_channel": sum(bool(s["channels"]) for s in swarms[:50]),
        "hubs": sw.get("hubs", [])[:10],
        "examples": [{"swarm_id": s["swarm_id"], "kind": s["kind"], "agents": s["n_agents"],
                      "example": s["example_texts"][:1], **{k: s["channels"][0][k] for k in (
                          "channel", "swarm_share", "enrichment", "distinct_operators", "lead_hours",
                          "first_poster_in_swarm", "p_bonferroni")}}
                     for s in swarms[:50] if s["channels"]],
    }

    for name in ("planted_eval.json", "precision.json", "early_warning.json"):
        d = load(R / name)
        if d is not None:
            out[name.removesuffix(".json")] = d.get("summary", d) if isinstance(d, dict) else d

    feb = load(R / "feb" / "swarms.json")
    if feb:
        out["contagion_window"] = feb["summary"]
    c = load(R / "feb" / "contagion.json")
    if c:
        res = c["results"]
        out["contagion"] = {
            "window_h": c["window_h"],
            "swarms_measured": len(res),
            "with_rr": sum(r["rr"] is not None for r in res),
            "rr_ci_above_1": sum(r["rr"] is not None and r["rr_ci95"][0] > 1 for r in res),
            "adopters_total": sum(r["adopters"] for r in res),
            "exposed_adopters_total": sum(r["exposed_adopters"] for r in res),
            "rows": [{k: r[k] for k in ("swarm_id", "kind", "example", "adopters", "exposed_adopters",
                                         "exposed_before_adoption_share", "exposed_nonadopters_at_risk",
                                         "adopt_rate_exposed", "adopt_rate_control", "rr", "rr_ci95",
                                         "placebo_rr", "placebo_ci95", "r_eff", "max_generation",
                                         "top_spreaders")} for r in res],
        }
    (R / "headline.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
