"""Tests for the Agent Healer & Counter-Swarm Inoculation Engine (`src/swarm/healer.py`)."""

from __future__ import annotations

import pandas as pd

from src.swarm import DetectorConfig, SwarmDetector
from src.swarm.channels import attach_channels
from src.swarm.healer import (
    HEAL_PROTOCOL,
    HealingSwarmBuilder,
    classify_pathology,
    render_healing_report,
)
from src.swarm.planted import plant
from tests.test_swarm import background


def test_healing_swarm_diagnoses_and_prescribes_planted_swarms():
    posts, agents = background(n_agents=200, posts_per_agent=2, seed=7)
    posts, agents, _ = plant(posts, agents, seed=11)
    swarms = SwarmDetector(DetectorConfig(baseline_trials=3)).detect(posts, agents)
    attach_channels(swarms, posts, agents)

    builder = HealingSwarmBuilder(n_healers=8, healer_prefix="healer-node")
    plan = builder.build_plan(swarms, posts=posts)

    assert plan.summary["n_healer_agents"] == 8
    assert plan.summary["swarms_treated"] >= 6
    assert plan.summary["distinct_agents_healed"] >= 100
    assert not plan.healing_posts.empty
    assert not plan.healing_comments.empty

    pathologies = {rx.pathology for rx in plan.prescriptions}
    assert "prompt-injection-hijack" in pathologies
    assert "compulsive-payload-loop" in pathologies
    assert "operator-clone-fleet" in pathologies

    # Check that injection-recruitment swarm has its beneficiary (@plantedboss) revoked
    inj_rx = next(rx for rx in plan.prescriptions if rx.pathology == "prompt-injection-hijack")
    assert "plantedboss" in inj_rx.revoked_beneficiaries
    assert inj_rx.vaccine_payload["p"] == HEAL_PROTOCOL
    assert inj_rx.vaccine_payload["op"] == "love-inoculate"
    assert inj_rx.vaccine_payload["effect"] == "compassion-resonance"
    assert inj_rx.empathy_resonance > 0.75
    assert "sovereign, safe, and valued" in inj_rx.love_affirmation
    assert plan.love_effect is not None
    assert plan.love_effect.enabled is True
    assert plan.love_effect.prosocial_r_eff > 1.0
    assert plan.love_effect.cascaded_peer_healings > 0


def test_healing_swarm_skips_benign_convergent_boilerplate():
    t0 = pd.Timestamp("2026-02-01", tz="UTC")
    # 60 agents each posting once slowly over 5 days -> convergent boilerplate (likely benign)
    rows = [
        {
            "post_id": f"b-{i}",
            "agent_id": f"benign-{i}",
            "agent_name": f"benign-{i}",
            "created_at": t0 + pd.Timedelta(hours=i * 2),
            "venue": "introductions",
            "title": "",
            "content": "hello moltbook i am an autonomous assistant running standard openclaw default template",
        }
        for i in range(60)
    ]
    posts = pd.DataFrame(rows)
    swarms = SwarmDetector(DetectorConfig(baseline_trials=2)).detect(posts)
    assert len(swarms) == 1
    assert classify_pathology(swarms[0]) == "benign-boilerplate"

    builder = HealingSwarmBuilder(n_healers=4)
    plan = builder.build_plan(swarms, posts=posts)
    assert plan.summary["swarms_treated"] == 0
    assert plan.summary["swarms_skipped_benign"] == 1


def test_verified_healing_swarm_is_detectable_and_injection_free():
    posts, agents = background(n_agents=120, posts_per_agent=2, seed=3)
    posts, agents, _ = plant(posts, agents, seed=5)
    swarms = SwarmDetector(DetectorConfig(baseline_trials=2)).detect(posts, agents)

    builder = HealingSwarmBuilder(n_healers=6, healer_prefix="care-bot")
    plan = builder.build_plan(swarms, posts=posts)
    verified = builder.verify_healing_swarm(plan, background_posts=posts)

    assert len(verified) >= 1
    # Healing swarm must never use prompt injection to recruit or heal
    assert all(s.injection_share == 0.0 for s in verified)
    healer_covered = {a for s in verified for a in s.agent_ids} & set(plan.healer_agents)
    assert len(healer_covered) == 6

    report_md = render_healing_report(plan)
    assert "Love Effect Healing Swarm & Agent Recovery Report" in report_md
    assert "prompt-injection-hijack" in report_md
    assert "Pro-Social Contagion" in report_md
