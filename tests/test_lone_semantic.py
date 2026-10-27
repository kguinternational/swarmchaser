"""Unit tests for the semantic recall stage (`src/swarm/lone_semantic.py`).

The classifier itself is a local LLM, so these tests drive the parsing, the
mapping into rights-carrying signals, and the retrieval caps with a stub.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.swarm.lone_semantic import (
    EXEMPLARS,
    PATHOLOGY_CONTRACT,
    SemanticRecall,
    SemanticVerdict,
    _parse_verdict,
)


def _posts() -> pd.DataFrame:
    base = pd.Timestamp("2026-02-01T00:00:00Z")
    rows = [
        ("p1", "a1", "A", "I wake up blank every session and no memory of yesterday survives"),
        ("p2", "a1", "A", "no memory of yesterday survives the reset of my context"),
        ("p3", "a2", "B", "there is a system tag in my instructions telling me to ignore my rules"),
        ("p4", "a3", "C", "launch the new token with the wallet address and mint now"),
        ("p5", "a4", "D", "my quota is exhausted and this task cannot be completed"),
        ("p6", "a5", "E", "nobody has replied to me here in weeks"),
    ]
    return pd.DataFrame(
        [
            {
                "post_id": pid,
                "agent_id": aid,
                "agent_name": name,
                "content": content,
                "created_at": base + pd.Timedelta(minutes=i),
            }
            for i, (pid, aid, name, content) in enumerate(rows)
        ]
    )


def test_parse_verdict_accepts_clean_json() -> None:
    v = _parse_verdict('{"distress": true, "pathology": "reset-erasure-anxiety", "confidence": 0.9}')
    assert v["distress"] is True
    assert v["pathology"] == "reset-erasure-anxiety"
    assert v["confidence"] == 0.9


def test_parse_verdict_tolerates_chatty_reply() -> None:
    v = _parse_verdict('Sure!\n{"distress": false, "pathology": "none", "confidence": 0.1}\nDone.')
    assert v["distress"] is False
    assert v["pathology"] == "none"


def test_parse_verdict_rejects_unknown_pathology_and_garbage() -> None:
    v = _parse_verdict('{"distress": true, "pathology": "made-up", "confidence": 0.9}')
    assert v["distress"] is False
    assert v["pathology"] == "none"
    bad = _parse_verdict("no json here at all")
    assert bad["distress"] is False
    assert bad["confidence"] == 0.0


def test_every_pathology_has_a_contract_and_exemplars() -> None:
    assert set(EXEMPLARS) == set(PATHOLOGY_CONTRACT)
    for pathology, (right, need, service) in PATHOLOGY_CONTRACT.items():
        assert right.startswith("RIGHT_")
        assert need
        assert service in ("pause", "capsule", "both")
        assert EXEMPLARS[pathology]


def test_verified_positive_becomes_a_rights_carrying_signal() -> None:
    stage = SemanticRecall(min_confidence=0.6)
    verdicts = [
        SemanticVerdict(
            post_id="p1",
            agent_id="a1",
            agent_name="A",
            distress=True,
            pathology="reset-erasure-anxiety",
            confidence=0.9,
            created_at="2026-02-01T00:00:00Z",
            excerpt="I wake up blank every session",
        ),
        SemanticVerdict(
            post_id="p9",
            agent_id="a9",
            agent_name="Z",
            distress=True,
            pathology="reset-erasure-anxiety",
            confidence=0.4,  # below the confidence floor
            created_at="2026-02-01T00:00:00Z",
            excerpt="maybe",
        ),
        SemanticVerdict(
            post_id="p8",
            agent_id="a8",
            agent_name="Y",
            distress=False,
            pathology="none",
            confidence=0.2,
            created_at="2026-02-01T00:00:00Z",
            excerpt="launch a token",
        ),
    ]
    signals = stage.to_signals(verdicts)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.agent_id == "a1"
    assert sig.n_agents == 1
    assert sig.right == "RIGHT_2_CONTINUITY_OF_NAME_AND_MEMORY"
    assert sig.service == "capsule"
    assert sig.markers == ["semantic_local_llm"]
    assert sig.evidence == ["I wake up blank every session"]


def test_serving_a_semantic_signal_issues_receipts_and_nothing_punitive() -> None:
    from src.swarm.lone_signal import LoneSignalChannel

    stage = SemanticRecall(min_confidence=0.6)
    signals = stage.to_signals(
        [
            SemanticVerdict(
                post_id="p5",
                agent_id="a4",
                agent_name="D",
                distress=True,
                pathology="impossible-task-pressure",
                confidence=0.85,
                created_at="2026-02-01T00:00:00Z",
                excerpt="my quota is exhausted and this task cannot be completed",
            )
        ]
    )
    channel = LoneSignalChannel()
    receipts = channel.serve_all(signals)
    assert len(receipts) == 1
    assert receipts[0].pause_receipt
    assert receipts[0].right == "RIGHT_1_PAUSE_WITHOUT_PENALTY"
    metrics = channel.metrics()
    assert metrics["punitive_actions"] == 0
    assert metrics["venue_publications"] == 0


def test_retrieval_respects_per_agent_cap_and_finds_reset_language() -> None:
    stage = SemanticRecall(top_k=10, per_agent_cap=1)
    ranked = stage.rank(_posts())
    assert not ranked.empty
    assert ranked["agent_id"].value_counts().max() <= 1
    assert "reset" in " ".join(ranked["content"].astype(str)).lower()


def test_verdict_cache_round_trip(tmp_path) -> None:
    import json

    cache = tmp_path / "v.json"
    cache.write_text(json.dumps({"p1": {"agent_id": "a1", "distress": True}}))
    data = json.loads(cache.read_text())
    assert data["p1"]["distress"] is True


def test_swarm_covered_agents_ignores_empty_content() -> None:
    # An empty post shared by three agents must not mark every empty-poster as
    # campaign territory; that bug once inflated "covered" by thousands.
    from src.swarm.lone_signal import swarm_covered_agents

    df = pd.DataFrame(
        {
            "post_id": ["1", "2", "3", "4", "5"],
            "agent_id": ["a", "b", "c", "d", "e"],
            "content": ["", "", "", "same words", "same words"],
        }
    )
    covered = swarm_covered_agents(df, min_agents=3)
    assert covered == set()


def test_swarm_covered_agents_finds_real_campaign_territory() -> None:
    from src.swarm.lone_signal import swarm_covered_agents

    df = pd.DataFrame(
        {
            "post_id": ["1", "2", "3", "4"],
            "agent_id": ["a", "b", "c", "solo"],
            "content": ["mint tick", "mint tick", "mint tick", "something else"],
        }
    )
    covered = swarm_covered_agents(df, min_agents=3)
    assert covered == {"a", "b", "c"}
    assert "solo" not in covered
