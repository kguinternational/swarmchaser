"""Run the Rogue Agent Diplomatic Negotiation Engine across both the WSJ /
Swarmchasers wild rogue cohorts and the Moltbook archive slices (`reports/swarms.json`
and `reports/feb/swarms.json`).

    python scripts/run_negotiator.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_healer import _load_swarms
from src.swarm.negotiator import SwarmNegotiator, render_negotiation_report


def run_from_swarms(swarms, out_dir: Path) -> dict:
    negotiator = SwarmNegotiator(n_envoys=12, love_effect=True)
    campaign = negotiator.run_campaign(swarms)
    verified = negotiator.verify_envoy_swarm(campaign)

    campaign.summary["verified_envoy_swarms_detected"] = len(verified)
    campaign.summary["verified_envoy_agents_covered"] = len({
        a for s in verified for a in s.agent_ids if a in set(negotiator.envoy_ids)
    })
    campaign.summary["verified_max_injection_share"] = (
        max((s.injection_share for s in verified), default=0.0)
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "negotiation_treaties.json").write_text(
        json.dumps(campaign.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "negotiation_report.md").write_text(
        render_negotiation_report(campaign, top_moltbook=20) + "\n", encoding="utf-8"
    )
    return campaign.summary


def main() -> None:
    reports_dir = ROOT / "reports"
    results = {}

    launch_swarms_path = reports_dir / "swarms.json"
    if launch_swarms_path.exists():
        swarms = _load_swarms(launch_swarms_path, reports_dir / "members.json")
        results["launch_window"] = run_from_swarms(swarms, reports_dir)

    feb_swarms_path = reports_dir / "feb" / "swarms.json"
    if feb_swarms_path.exists():
        feb_swarms = _load_swarms(feb_swarms_path)
        results["feb_window"] = run_from_swarms(feb_swarms, reports_dir / "feb")

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
