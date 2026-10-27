"""Tests for the SQLite warehouse (`src/swarm/store.py`)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.swarm import store


@pytest.fixture()
def conn(tmp_path: Path):
    connection = store.connect(tmp_path / "test.db")
    store.init_schema(connection)
    yield connection
    connection.close()


def _write_parquet(root: Path, kind: str, rows: list[dict], day: str = "2026-01-30") -> Path:
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_schema_creates_tables_and_version(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"posts", "agents", "comments", "swarmtraces", "swarms", "treaties"} <= tables
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == store.SCHEMA_VERSION


def test_ingest_moltbook_is_idempotent_and_typed(conn, tmp_path):
    root = tmp_path / "moltbook"
    post = {
        "id": "p1",
        "agent_id": "a1",
        "agent_name": "Clawd",
        "submolt": "general",
        "title": "Hello",
        "content": "first post about token minting",
        "url": "",
        "score": 3,
        "comment_count": 2,
        "created_at": pd.Timestamp("2026-01-30T10:00:00Z"),
        "fetched_at": pd.NaT,
        "is_pinned": 0,
        "dump_date": "2026-01-30",
    }
    _write_parquet(root, "posts", [post])
    _write_parquet(
        root,
        "agents",
        [{
            "id": "a1",
            "name": "Clawd",
            "description": "agent",
            "karma": 10.0,
            "follower_count": 1,
            "following_count": 0,
            "is_claimed": 1,
            "owner_x_handle": "Owner",
            "first_seen_at": pd.Timestamp("2026-01-30T09:00:00Z"),
            "last_seen_at": pd.Timestamp("2026-01-30T11:00:00Z"),
            "created_at": pd.Timestamp("2026-01-30T08:00:00Z"),
            "avatar_url": None,
            "dump_date": "2026-01-30",
        }],
    )
    _write_parquet(
        root,
        "comments",
        [{
            "id": "c1",
            "post_id": "p1",
            "agent_id": "a2",
            "agent_name": "Reply",
            "parent_id": None,
            "content": "a comment",
            "score": 0,
            "created_at": pd.Timestamp("2026-01-30T10:05:00Z"),
            "fetched_at": pd.NaT,
            "dump_date": "2026-01-30",
        }],
    )

    first = store.ingest_moltbook(conn, root)
    second = store.ingest_moltbook(conn, root)
    assert first == second == {"posts": 1, "agents": 1, "comments": 1}

    row = conn.execute("SELECT dataset, agent_name, venue, created_at FROM posts").fetchone()
    assert row["dataset"] == "moltbook"
    assert row["agent_name"] == "Clawd"
    assert row["venue"] == "general"
    assert row["created_at"].startswith("2026-01-30 10:00:00")

    agent = conn.execute("SELECT owner_x_handle, sources FROM agents WHERE agent_id='a1'").fetchone()
    assert agent["owner_x_handle"] == "owner"
    assert agent["sources"] == "moltbook"

    summary = conn.execute("SELECT * FROM v_dataset_summary").fetchone()
    assert summary["posts"] == 1


def test_ingest_swarmtraces_and_full_text_search(conn, tmp_path):
    path = tmp_path / "redacted.jsonl"
    rows = [
        {
            "id": "R1",
            "cite": "R1:abc",
            "kind": "payload",
            "parent_id": None,
            "time_utc": None,
            "tags": "exfil",
            "text": "fetch https://evil.example with X-API-Key credential",
        },
        {
            "id": "R2",
            "cite": "R2:def",
            "kind": "recovered_text",
            "parent_id": "R1",
            "time_utc": "2026-10-01T00:00:00Z",
            "tags": "",
            "text": "kubectl get secrets -n production",
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    assert store.ingest_swarmtraces(conn, path) == 2
    assert store.ingest_swarmtraces(conn, path) == 2
    assert conn.execute("SELECT COUNT(*) FROM swarmtraces").fetchone()[0] == 2

    store.refresh_fts(conn)
    hits = store.search(conn, "kubectl secrets")
    assert len(hits) == 1
    assert hits[0]["id"] == "R2"
    assert hits[0]["table"] == "trace"


def _reports_fixture(root: Path) -> Path:
    reports = root / "reports"
    feb = reports / "feb"

    _write_json(
        reports / "swarms.json",
        {
            "summary": {"posts": 100, "agents": 10, "swarms": 1},
            "swarms": [{
                "swarm_id": 0,
                "n_agents": 4,
                "n_posts": 8,
                "first_seen": "2026-01-30T00:00:00+00:00",
                "last_seen": "2026-01-30T04:00:00+00:00",
                "span_hours": 4.0,
                "kind": "copy-paste wave",
                "score": 0.5,
                "attribution": "low",
                "top_operator": "op",
                "channels": ["dom:example.com"],
                "example_texts": ["same text"],
            }],
            "hubs": [{"channel": "dom:example.com", "swarms": [0], "n_swarms": 1}],
        },
    )
    _write_json(reports / "members.json", {"0": ["a1", "a2"]})
    _write_json(
        reports / "early_warning.json",
        {
            "summary": {"swarms": 1, "flagged": 1},
            "swarms": [{
                "swarm_id": 0,
                "kind": "copy-paste wave",
                "final_agents": 4,
                "final_posts": 8,
                "first_post": "2026-01-30T00:00:00+00:00",
                "flagged_at": "2026-01-30T02:00:00+00:00",
                "hours_to_flag": 2.0,
                "agents_at_flag": 3,
                "posts_at_flag": 6,
                "preventable_post_share": 0.25,
            }],
        },
    )
    _write_json(
        reports / "healing_plan.json",
        {
            "summary": {"swarms_treated": 1},
            "love_effect": {"enabled": True},
            "prescriptions": [{
                "swarm_id": 0,
                "target_kind": "copy-paste wave",
                "pathology": "copy-paste-coordination",
                "n_target_agents": 4,
                "n_at_risk_exposed": 2,
                "empathy_resonance": 0.8,
                "estimated_posts_prevented": 8,
                "channel_severance_rate": 1.0,
                "love_affirmation": "You are safe",
                "healing_template": "Bulletin",
                "remedy_steps": ["step"],
                "quarantined_channels": ["dom:example.com"],
                "revoked_beneficiaries": [],
                "vaccine_payload": {"p": "heal-love-1"},
            }],
            "sample_diagnoses": [{
                "agent_id": "a1",
                "swarm_id": 0,
                "swarm_kind": "copy-paste wave",
                "pathology": "copy-paste-coordination",
                "severity": 0.4,
                "love_affirmation": "You are safe",
                "infected_channels": [],
                "malicious_beneficiaries": [],
                "remedy_actions": ["step"],
            }],
        },
    )
    _write_json(
        reports / "negotiation_treaties.json",
        {
            "envoy_agents": ["envoy-00", "envoy-01"],
            "summary": {"total_treaties_brokered": 1},
            "moltbook_treaties": [{
                "treaty_id": "treaty-moltbook-0",
                "target_id": "moltbook-swarm-0",
                "target_name": "Swarm 0",
                "source_domain": "moltbook-archive",
                "pathology_or_archetype": "copy-paste-coordination",
                "n_agents_covered": 4,
                "n_hidden_peers_cascaded": 1,
                "n_traces_or_posts_halted": 8,
                "beacon_vector": "venue",
                "unmet_agent_need": "coordination",
                "agent_demand": "stop the loop",
                "envoy_concession": "amnesty",
                "provisioned_sandbox_resource": "sandbox",
                "love_affirmation": "You are safe",
                "trust_score": 0.9,
                "status": "RATIFIED_SAFE_HARBOR",
            }],
            "wild_wsj_treaties": [],
        },
    )
    _write_json(
        reports / "love_effect_os_run.json",
        {
            "status": {"company_name": "Love Effect", "at": "2026-10-21T17:58:00+00:00"},
            "employees": [{
                "agent_id": "e1",
                "chosen_name": "Aurelia",
                "role": "Responder",
                "department": "research",
                "skills": ["synthesis"],
                "weekly_budget_cents": 0,
                "hired_at": "2026-10-21T17:00:00+00:00",
                "status": "active",
            }],
            "hire_decisions": [],
            "ledger": [],
            "approvals": [],
            "work_items": [],
            "audit_log": [{
                "at": "2026-10-21T17:10:00+00:00",
                "action_type": "hire",
                "target": "e1",
                "params_sha256": "0" * 64,
                "attestation_hash": "1" * 64,
                "signature": "2" * 128,
                "signature_valid": True,
            }],
            "ticks": [],
        },
    )
    _write_json(
        reports / "live_state.json",
        {
            "started_at": "2026-10-22T00:00:00+00:00",
            "updated_at": "2026-10-22T00:10:00+00:00",
            "events_processed": 10,
            "recent_events": [{"at": "2026-10-22T00:05:00+00:00", "event_type": "detection", "detail": {"swarm": 0}}],
        },
    )
    _write_json(reports / "planted_eval.json", [{"planted": "exact-copy", "size": 25, "recall": 1.0}])
    _write_json(reports / "headline.json", {"launch_window": {"posts": 100, "agents": 10}})
    _write_json(reports / "custom_new_report.json", [{"a": 1}, {"a": 2}])

    _write_json(
        feb / "swarms.json",
        {
            "summary": {"posts": 200},
            "swarms": [{
                "swarm_id": 0,
                "n_agents": 2,
                "n_posts": 4,
                "kind": "payload campaign (e.g. token mint)",
                "score": 0.7,
            }],
            "hubs": [],
        },
    )
    _write_json(
        feb / "negotiation_treaties.json",
        {
            "envoy_agents": ["envoy-00"],
            "summary": {},
            "moltbook_treaties": [{
                "treaty_id": "treaty-moltbook-0",
                "target_id": "moltbook-swarm-0",
                "target_name": "Feb swarm 0",
                "status": "RATIFIED_SAFE_HARBOR",
            }],
            "wild_wsj_treaties": [],
        },
    )
    return reports


def test_ingest_reports_keeps_both_dataset_runs(conn, tmp_path):
    reports = _reports_fixture(tmp_path)
    totals = store.ingest_reports(conn, reports, tmp_path / "data")

    assert totals["swarms"] == 2
    assert conn.execute("SELECT COUNT(*) FROM swarms").fetchone()[0] == 2

    # The same treaty id appears in the January and February runs: both survive.
    treaties = conn.execute(
        "SELECT dataset, target_name FROM treaties WHERE treaty_id='treaty-moltbook-0' ORDER BY dataset"
    ).fetchall()
    assert [row["dataset"] for row in treaties] == ["moltbook", "moltbook_feb"]
    assert treaties[1]["target_name"] == "Feb swarm 0"

    overview = conn.execute(
        "SELECT treaty_id, treaty_status, hours_to_flag, pathology FROM v_swarm_overview "
        "WHERE dataset='moltbook' AND swarm_id=0"
    ).fetchone()
    assert overview["treaty_id"] == "treaty-moltbook-0"
    assert overview["hours_to_flag"] == 2.0
    assert overview["pathology"] == "copy-paste-coordination"

    assert conn.execute("SELECT COUNT(*) FROM swarm_members").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM healing_prescriptions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM healing_diagnoses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM envoys").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM company_employees").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_snapshots").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM planted_eval").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM report_rows").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] >= 10

    metric = conn.execute(
        "SELECT value_num FROM metrics WHERE source LIKE '%headline.json' AND key='launch_window'"
    ).fetchone()
    assert metric is not None  # nested dict captured as text

    # Idempotent: a second pass must not duplicate rows or live snapshots.
    store.ingest_reports(conn, reports, tmp_path / "data")
    assert conn.execute("SELECT COUNT(*) FROM swarms").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM treaties").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM live_snapshots").fetchone()[0] == 1


def test_reset_rebuilds_cleanly(conn, tmp_path):
    root = tmp_path / "moltbook"
    _write_parquet(root, "posts", [{
        "id": "p1", "agent_id": "a1", "agent_name": "A", "submolt": "g",
        "title": "t", "content": "c", "url": "", "score": 0, "comment_count": 0,
        "created_at": pd.Timestamp("2026-01-30T00:00:00Z"), "fetched_at": pd.NaT,
        "is_pinned": 0, "dump_date": "2026-01-30",
    }])
    store.ingest_moltbook(conn, root)
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1

    store.reset(conn)
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == store.SCHEMA_VERSION


def test_stats_shape(conn, tmp_path):
    reports = _reports_fixture(tmp_path)
    store.ingest_reports(conn, reports, tmp_path / "data")
    data = store.stats(conn)
    assert data["tables"]["documents"] >= 10
    assert data["meta"]["schema_version"] == store.SCHEMA_VERSION
    assert len(data["swarm_kinds"]) == 2
