"""Generate the Healing Swarm plan and recovery report from detected Moltbook swarms.

Runs offline against the committed detection outputs in `reports/swarms.json`,
`reports/members.json`, `reports/early_warning.json`, and
`reports/feb/contagion.json` (plus `reports/feb/swarms.json`), writing:

- `reports/healing_plan.json`
- `reports/healing_report.md`
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm.contagion import ContagionResult
from src.swarm.detector import Swarm
from src.swarm.healer import HealingSwarmBuilder, render_healing_report


def _load_swarms(swarms_path: Path, members_path: Path | None = None) -> list[Swarm]:
    data = json.loads(swarms_path.read_text())
    members_map: dict[int, list[str] | dict] = {}
    if members_path and members_path.exists():
        raw_m = json.loads(members_path.read_text())
        if isinstance(raw_m, list):
            members_map = {int(item["swarm_id"]): item for item in raw_m}
        elif isinstance(raw_m, dict):
            members_map = {int(k): v for k, v in raw_m.items()}

    out: list[Swarm] = []
    for row in data["swarms"]:
        sid = int(row["swarm_id"])
        m = members_map.get(sid, {})
        if isinstance(m, list):
            agent_ids = list(m)
            post_ids = [f"swarm{sid}-post-{i:04d}" for i in range(min(row["n_posts"], 20))]
        else:
            agent_ids = list(m.get("agent_ids") or row.get("sample_agents") or [])
            if len(agent_ids) < row["n_agents"]:
                agent_ids.extend(
                    f"swarm{sid}-member-{i:06d}" for i in range(row["n_agents"] - len(agent_ids))
                )
            post_ids = m.get("post_ids") or [f"swarm{sid}-post-{i:04d}" for i in range(min(row["n_posts"], 20))]
        out.append(
            Swarm(
                swarm_id=sid,
                n_agents=row["n_agents"],
                n_posts=row["n_posts"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                span_hours=row["span_hours"],
                kind=row["kind"],
                score=row["score"],
                synchrony=row["synchrony"],
                synchrony_baseline=row["synchrony_baseline"],
                synchrony_lift=row["synchrony_lift"],
                burst_lift=row.get("burst_lift", 1.0),
                peak_posts_per_10min=row["peak_posts_per_10min"],
                scripted_cadence_share=row["scripted_cadence_share"],
                registration_burst_share=row["registration_burst_share"],
                injection_share=row["injection_share"],
                operators_known=row["operators_known"],
                distinct_operators=row["distinct_operators"],
                top_operator=row["top_operator"],
                top_operator_share=row["top_operator_share"],
                attribution=row["attribution"],
                text_similarity=row.get("text_similarity", 1.0),
                beneficiaries=row.get("beneficiaries", []),
                top_venues=row.get("top_venues", []),
                key_families=row.get("key_families", {}),
                example_texts=row.get("example_texts", []),
                sample_agents=row.get("sample_agents", []),
                agent_ids=agent_ids,
                post_ids=post_ids,
                channels=row.get("channels", []),
            )
        )
    return out


def main() -> None:
    reports_dir = ROOT / "reports"
    swarms = _load_swarms(reports_dir / "swarms.json", reports_dir / "members.json")

    ew_map: dict[int, dict] = {}
    ew_path = reports_dir / "early_warning.json"
    if ew_path.exists():
        ew_data = json.loads(ew_path.read_text())
        rows = ew_data.get("swarms", ew_data.get("rows", ew_data if isinstance(ew_data, list) else []))
        for r in rows:
            sid = int(r["swarm_id"])
            if "posts_after_flag" not in r and "final_posts" in r and "posts_at_flag" in r:
                r = dict(r, posts_after_flag=max(0, int(r["final_posts"]) - int(r["posts_at_flag"])))
            ew_map[sid] = r

    cont_map: dict[int, ContagionResult] = {}
    cont_path = reports_dir / "feb" / "contagion.json"
    if cont_path.exists():
        cont_data = json.loads(cont_path.read_text())
        for r in cont_data.get("results", cont_data.get("rows", [])):
            cont_map[int(r["swarm_id"])] = ContagionResult(
                swarm_id=int(r["swarm_id"]),
                kind=r["kind"],
                adopters=r["adopters"],
                exposed_adopters=r["exposed_adopters"],
                exposed_before_adoption_share=r["exposed_before_adoption_share"],
                exposed_nonadopters_at_risk=r["exposed_nonadopters_at_risk"],
                rr=r["rr"],
                rr_ci95=tuple(r["rr_ci95"]) if r.get("rr_ci95") else None,
                adopt_rate_exposed=r["adopt_rate_exposed"],
                adopt_rate_control=r["adopt_rate_control"],
                placebo_rr=r["placebo_rr"],
                placebo_ci95=tuple(r["placebo_ci95"]) if r.get("placebo_ci95") else None,
                placebo_swarm=r.get("placebo_swarm"),
                r_eff=r["r_eff"],
                max_generation=r["max_generation"],
                patient_zero=r.get("patient_zero"),
                top_spreaders=[tuple(x) for x in r.get("top_spreaders", [])],
            )

    builder = HealingSwarmBuilder(n_healers=12, healer_prefix="healer-guardian")
    plan = builder.build_plan(
        swarms,
        early_warning_by_swarm=ew_map,
    )

    # Also build the February contagion-window healing plan if feb/swarms.json exists
    feb_swarms_path = reports_dir / "feb" / "swarms.json"
    if feb_swarms_path.exists():
        feb_swarms = _load_swarms(feb_swarms_path)
        feb_plan = builder.build_plan(feb_swarms, contagion_by_swarm=cont_map)
        (reports_dir / "feb" / "healing_plan.json").write_text(json.dumps(feb_plan.to_dict(), indent=2) + "\n")
        (reports_dir / "feb" / "healing_report.md").write_text(render_healing_report(feb_plan, top=25) + "\n")
        plan.summary["feb_window_healing"] = {
            "swarms_treated": feb_plan.summary["swarms_treated"],
            "distinct_agents_healed": feb_plan.summary["distinct_agents_healed"],
            "cascaded_peer_healings_via_love_effect": feb_plan.summary["cascaded_peer_healings_via_love_effect"],
            "total_agents_uplifted": feb_plan.summary["total_agents_uplifted"],
            "at_risk_agents_inoculated": feb_plan.summary["at_risk_agents_inoculated"],
            "quarantined_channels_count": feb_plan.summary["quarantined_channels_count"],
            "estimated_posts_prevented": feb_plan.summary["estimated_posts_prevented"],
            "love_effect": feb_plan.summary["love_effect"],
        }

    # Verify the Healing Swarm is itself detectable as an auditable campaign
    verified = builder.verify_healing_swarm(plan)
    plan.summary["verified_healing_campaigns"] = len(verified)
    plan.summary["verified_healer_coverage"] = (
        round(len({a for s in verified for a in s.agent_ids} & set(plan.healer_agents)) / len(plan.healer_agents), 3)
        if plan.healer_agents else 0.0
    )

    out_json = reports_dir / "healing_plan.json"
    out_md = reports_dir / "healing_report.md"
    out_json.write_text(json.dumps(plan.to_dict(), indent=2) + "\n")
    out_md.write_text(render_healing_report(plan, top=25) + "\n")
    print(json.dumps(plan.summary, indent=2))


if __name__ == "__main__":
    main()
