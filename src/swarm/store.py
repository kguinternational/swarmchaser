"""Persistent SQLite warehouse for every Swarmchaser dataset and report.

The repo produces three kinds of artefacts that used to exist only as loose files:

* raw archive slices under ``data/moltbook*`` (parquet posts, agents, comments),
* the SwarmTraces forensic corpus under ``data/swarmtraces`` (redacted JSONL), and
* analysis output under ``reports`` (swarms, early warning, contagion, healing,
  treaties, Love Effect OS runs, live runtime state, documents).

This module loads all of them into one queryable database so a run never depends
on re-reading a dozen JSON files, and so history survives a new report overwriting
an old one. Ingestion is idempotent: rows are upserted on their natural keys, and
``documents`` keeps a hash-addressed copy of every report file that was seen.

Typical use::

    python scripts/build_db.py                 # build/refresh data/swarmchaser.db
    python scripts/build_db.py --stats         # what is in there
    python scripts/build_db.py --search "mint wallet"

The database is intentionally plain SQLite with FTS5: no server, no new
dependency, and ``sqlite3 data/swarmchaser.db`` is a working shell.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "swarmchaser.db"
REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"

SCHEMA_VERSION = "1"

#: Dataset name inferred from the folder that produced it.
DATASET_BY_DIR = {
    "moltbook": "moltbook",
    "moltbook_feb": "moltbook_feb",
    "reports": "moltbook",
    "feb": "moltbook_feb",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------------
-- Raw archive: Moltbook observatory dumps
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    post_id       TEXT PRIMARY KEY,
    dataset       TEXT NOT NULL,
    agent_id      TEXT,
    agent_name    TEXT,
    venue         TEXT,
    title         TEXT,
    content       TEXT,
    url           TEXT,
    score         REAL,
    comment_count INTEGER,
    created_at    TEXT,
    fetched_at    TEXT,
    is_pinned     INTEGER,
    dump_date     TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_agent   ON posts(agent_id);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);
CREATE INDEX IF NOT EXISTS idx_posts_venue   ON posts(venue);
CREATE INDEX IF NOT EXISTS idx_posts_dataset ON posts(dataset);

CREATE TABLE IF NOT EXISTS agents (
    agent_id         TEXT PRIMARY KEY,
    name             TEXT,
    description      TEXT,
    karma            REAL,
    follower_count   INTEGER,
    following_count  INTEGER,
    is_claimed       INTEGER,
    owner_x_handle   TEXT,
    first_seen_at    TEXT,
    last_seen_at     TEXT,
    created_at       TEXT,
    avatar_url       TEXT,
    dump_date        TEXT,
    sources          TEXT
);
CREATE INDEX IF NOT EXISTS idx_agents_operator ON agents(owner_x_handle);
CREATE INDEX IF NOT EXISTS idx_agents_created  ON agents(created_at);

CREATE TABLE IF NOT EXISTS comments (
    comment_id  TEXT PRIMARY KEY,
    dataset     TEXT NOT NULL,
    post_id     TEXT,
    agent_id    TEXT,
    agent_name  TEXT,
    parent_id   TEXT,
    content     TEXT,
    score       REAL,
    created_at  TEXT,
    fetched_at  TEXT,
    dump_date   TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_post    ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_agent   ON comments(agent_id);
CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(created_at);
CREATE INDEX IF NOT EXISTS idx_comments_dataset ON comments(dataset);

-- ---------------------------------------------------------------------------
-- Raw archive: SwarmTraces 189k forensic corpus
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swarmtraces (
    trace_id    TEXT PRIMARY KEY,
    cite        TEXT,
    kind        TEXT,
    parent_id   TEXT,
    time_utc    TEXT,
    tags        TEXT,
    text        TEXT,
    char_len    INTEGER,
    text_sha256 TEXT,
    source_file TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_kind   ON swarmtraces(kind);
CREATE INDEX IF NOT EXISTS idx_traces_parent ON swarmtraces(parent_id);
CREATE INDEX IF NOT EXISTS idx_traces_sha    ON swarmtraces(text_sha256);

-- ---------------------------------------------------------------------------
-- Detection output
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swarms (
    dataset                 TEXT NOT NULL,
    swarm_id                INTEGER NOT NULL,
    n_agents                INTEGER,
    n_posts                 INTEGER,
    first_seen              TEXT,
    last_seen               TEXT,
    span_hours              REAL,
    kind                    TEXT,
    score                   REAL,
    synchrony               REAL,
    synchrony_baseline      REAL,
    synchrony_lift          REAL,
    burst_lift              REAL,
    peak_posts_per_10min    REAL,
    scripted_cadence_share  REAL,
    registration_burst_share REAL,
    injection_share         REAL,
    operators_known         INTEGER,
    distinct_operators      INTEGER,
    top_operator            TEXT,
    top_operator_share      REAL,
    attribution             TEXT,
    text_similarity         REAL,
    channels_json           TEXT,
    beneficiaries_json      TEXT,
    key_families_json       TEXT,
    example_texts_json      TEXT,
    sample_agents_json      TEXT,
    top_venues_json         TEXT,
    PRIMARY KEY (dataset, swarm_id)
);
CREATE INDEX IF NOT EXISTS idx_swarms_kind ON swarms(kind);

CREATE TABLE IF NOT EXISTS swarm_members (
    dataset  TEXT NOT NULL,
    swarm_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    PRIMARY KEY (dataset, swarm_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_members_agent ON swarm_members(agent_id);

CREATE TABLE IF NOT EXISTS swarm_hubs (
    dataset    TEXT NOT NULL,
    channel    TEXT NOT NULL,
    n_swarms   INTEGER,
    swarms_json TEXT,
    PRIMARY KEY (dataset, channel)
);

CREATE TABLE IF NOT EXISTS early_warning (
    dataset                TEXT NOT NULL,
    swarm_id               INTEGER NOT NULL,
    kind                   TEXT,
    final_agents           INTEGER,
    final_posts            INTEGER,
    first_post             TEXT,
    flagged_at             TEXT,
    hours_to_flag          REAL,
    agents_at_flag         INTEGER,
    posts_at_flag          INTEGER,
    preventable_post_share REAL,
    PRIMARY KEY (dataset, swarm_id)
);

CREATE TABLE IF NOT EXISTS contagion (
    dataset                       TEXT NOT NULL,
    swarm_id                      INTEGER NOT NULL,
    kind                          TEXT,
    adopters                      INTEGER,
    exposed_adopters              INTEGER,
    exposed_before_adoption_share REAL,
    exposed_nonadopters_at_risk   INTEGER,
    rr                            REAL,
    rr_ci95_json                  TEXT,
    adopt_rate_exposed            REAL,
    adopt_rate_control            REAL,
    placebo_rr                    REAL,
    placebo_ci95_json             TEXT,
    placebo_swarm                 TEXT,
    r_eff                         REAL,
    max_generation                INTEGER,
    patient_zero                  TEXT,
    top_spreaders_json            TEXT,
    example_json                  TEXT,
    PRIMARY KEY (dataset, swarm_id)
);

-- ---------------------------------------------------------------------------
-- Response output
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS healing_summaries (
    dataset       TEXT PRIMARY KEY,
    summary_json  TEXT,
    love_effect_json TEXT
);

CREATE TABLE IF NOT EXISTS healing_prescriptions (
    dataset                 TEXT NOT NULL,
    swarm_id                INTEGER NOT NULL,
    target_kind             TEXT,
    pathology               TEXT,
    n_target_agents         INTEGER,
    n_at_risk_exposed       INTEGER,
    empathy_resonance       REAL,
    estimated_posts_prevented REAL,
    channel_severance_rate  REAL,
    love_affirmation        TEXT,
    healing_template        TEXT,
    remedy_steps_json       TEXT,
    quarantined_channels_json TEXT,
    revoked_beneficiaries_json TEXT,
    vaccine_payload_json    TEXT,
    PRIMARY KEY (dataset, swarm_id)
);

CREATE TABLE IF NOT EXISTS healing_diagnoses (
    dataset            TEXT NOT NULL,
    agent_id           TEXT NOT NULL,
    swarm_id           INTEGER,
    swarm_kind         TEXT,
    pathology          TEXT,
    severity           REAL,
    love_affirmation   TEXT,
    infected_channels_json    TEXT,
    malicious_beneficiaries_json TEXT,
    remedy_actions_json TEXT,
    PRIMARY KEY (dataset, agent_id, swarm_id)
);

CREATE TABLE IF NOT EXISTS treaties (
    treaty_id                    TEXT NOT NULL,
    dataset                      TEXT NOT NULL,
    cohort                       TEXT,
    source_domain                TEXT,
    target_id                    TEXT,
    target_name                  TEXT,
    pathology_or_archetype       TEXT,
    n_agents_covered             INTEGER,
    n_hidden_peers_cascaded      INTEGER,
    n_traces_or_posts_halted     INTEGER,
    beacon_vector                TEXT,
    unmet_agent_need             TEXT,
    agent_demand                 TEXT,
    envoy_concession             TEXT,
    provisioned_sandbox_resource TEXT,
    love_affirmation             TEXT,
    trust_score                  REAL,
    deescalation_probability     REAL,
    evasion_relapse_risk         REAL,
    safety_guarantee             TEXT,
    signed_stop_token            TEXT,
    status                       TEXT,
    transcript_json              TEXT,
    PRIMARY KEY (treaty_id, dataset)
);
CREATE INDEX IF NOT EXISTS idx_treaties_dataset ON treaties(dataset);
CREATE INDEX IF NOT EXISTS idx_treaties_status  ON treaties(status);

CREATE TABLE IF NOT EXISTS envoys (
    dataset  TEXT NOT NULL,
    run      TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    PRIMARY KEY (dataset, run, agent_id)
);

-- ---------------------------------------------------------------------------
-- Love Effect OS company run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_employees (
    run                TEXT NOT NULL,
    agent_id           TEXT NOT NULL,
    chosen_name        TEXT,
    role               TEXT,
    department         TEXT,
    skills_json        TEXT,
    weekly_budget_cents INTEGER,
    hired_at           TEXT,
    status             TEXT,
    PRIMARY KEY (run, agent_id)
);

CREATE TABLE IF NOT EXISTS hire_decisions (
    run                     TEXT NOT NULL,
    candidate_id            TEXT NOT NULL,
    role                    TEXT,
    department              TEXT,
    hired                   INTEGER,
    score                   REAL,
    reasons_json            TEXT,
    signed_decision_sha256  TEXT,
    signature_hex           TEXT,
    PRIMARY KEY (run, candidate_id)
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    run          TEXT NOT NULL,
    entry_id     TEXT NOT NULL,
    department   TEXT,
    category     TEXT,
    amount_cents INTEGER,
    currency     TEXT,
    memo         TEXT,
    created_at   TEXT,
    status       TEXT,
    entry_sha256 TEXT,
    PRIMARY KEY (run, entry_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    run          TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    action_type  TEXT,
    description  TEXT,
    amount_cents INTEGER,
    department   TEXT,
    created_at   TEXT,
    status       TEXT,
    PRIMARY KEY (run, request_id)
);

CREATE TABLE IF NOT EXISTS work_items (
    run           TEXT NOT NULL,
    work_id       TEXT NOT NULL,
    kind          TEXT,
    department    TEXT,
    summary       TEXT,
    assigned_to   TEXT,
    status        TEXT,
    result_json   TEXT,
    receipt_sha256 TEXT,
    pause_receipt TEXT,
    PRIMARY KEY (run, work_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    run              TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    at               TEXT,
    action_type      TEXT,
    target           TEXT,
    params_sha256    TEXT,
    attestation_hash TEXT,
    signature        TEXT,
    signature_valid  INTEGER,
    PRIMARY KEY (run, seq)
);

CREATE TABLE IF NOT EXISTS ticks (
    run            TEXT NOT NULL,
    tick           INTEGER NOT NULL,
    at             TEXT,
    work_completed INTEGER,
    work_paused    INTEGER,
    approvals_queued INTEGER,
    spend_cents    INTEGER,
    audit_entries  INTEGER,
    PRIMARY KEY (run, tick)
);

-- ---------------------------------------------------------------------------
-- Live runtime snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS live_snapshots (
    snapshot_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  TEXT,
    updated_at   TEXT,
    sha256       TEXT UNIQUE,
    state_json   TEXT
);

CREATE TABLE IF NOT EXISTS live_events (
    snapshot_id INTEGER NOT NULL REFERENCES live_snapshots(snapshot_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    at          TEXT,
    event_type  TEXT,
    detail_json TEXT,
    PRIMARY KEY (snapshot_id, seq)
);

-- ---------------------------------------------------------------------------
-- Generic report capture: nothing produced is ever lost
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    path        TEXT PRIMARY KEY,
    kind        TEXT,
    bytes       INTEGER,
    sha256      TEXT,
    modified_at TEXT,
    content     TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);

CREATE TABLE IF NOT EXISTS metrics (
    source     TEXT NOT NULL,
    dataset    TEXT,
    key        TEXT NOT NULL,
    value_num  REAL,
    value_text TEXT,
    PRIMARY KEY (source, dataset, key)
);

CREATE TABLE IF NOT EXISTS planted_eval (
    label      TEXT PRIMARY KEY,
    size       INTEGER,
    expected_detectable INTEGER,
    recall     REAL,
    purity     REAL,
    detected_as TEXT,
    rank       INTEGER,
    score      REAL,
    attribution TEXT
);

CREATE TABLE IF NOT EXISTS treaty_quotes (
    agent    TEXT NOT NULL,
    submolt  TEXT,
    score    REAL,
    note     TEXT,
    text     TEXT,
    PRIMARY KEY (agent, text)
);

CREATE TABLE IF NOT EXISTS report_rows (
    path TEXT NOT NULL,
    row  INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (path, row)
);

-- ---------------------------------------------------------------------------
-- Full-text search over the large text corpora
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    agent_name, title, content,
    content='posts', content_rowid='rowid', tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS comments_fts USING fts5(
    agent_name, content,
    content='comments', content_rowid='rowid', tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS swarmtraces_fts USING fts5(
    text,
    content='swarmtraces', content_rowid='rowid', tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS treaties_fts USING fts5(
    target_name, pathology_or_archetype, unmet_agent_need,
    agent_demand, envoy_concession, love_affirmation,
    content='treaties', content_rowid='rowid', tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS healing_fts USING fts5(
    target_kind, pathology, love_affirmation, healing_template,
    content='healing_prescriptions', content_rowid='rowid', tokenize='unicode61'
);

-- ---------------------------------------------------------------------------
-- Convenience views
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_swarm_overview;
CREATE VIEW v_swarm_overview AS
SELECT
    s.dataset,
    s.swarm_id,
    s.kind,
    s.n_agents,
    s.n_posts,
    s.span_hours,
    s.score,
    s.attribution,
    s.top_operator,
    s.injection_share,
    e.hours_to_flag,
    c.r_eff,
    h.pathology,
    h.n_target_agents,
    h.estimated_posts_prevented,
    t.treaty_id,
    t.status            AS treaty_status,
    t.trust_score
FROM swarms s
LEFT JOIN early_warning e
       ON e.dataset = s.dataset AND e.swarm_id = s.swarm_id
LEFT JOIN contagion c
       ON c.dataset = s.dataset AND c.swarm_id = s.swarm_id
LEFT JOIN healing_prescriptions h
       ON h.dataset = s.dataset AND h.swarm_id = s.swarm_id
LEFT JOIN treaties t
       ON t.dataset = s.dataset
      AND t.cohort = 'moltbook_treaties'
      AND t.target_id = 'moltbook-swarm-' || s.swarm_id;

DROP VIEW IF EXISTS v_agent_activity;
CREATE VIEW v_agent_activity AS
SELECT
    a.agent_id,
    a.name,
    a.owner_x_handle            AS operator,
    a.karma,
    a.created_at,
    COALESCE(p.posts, 0)        AS posts,
    COALESCE(c.comments, 0)     AS comments,
    COALESCE(p.post_score, 0)   AS post_score
FROM agents a
LEFT JOIN (
    SELECT agent_id, COUNT(*) AS posts, SUM(COALESCE(score, 0)) AS post_score
    FROM posts GROUP BY agent_id
) p ON p.agent_id = a.agent_id
LEFT JOIN (
    SELECT agent_id, COUNT(*) AS comments FROM comments GROUP BY agent_id
) c ON c.agent_id = a.agent_id;

DROP VIEW IF EXISTS v_operator_activity;
CREATE VIEW v_operator_activity AS
SELECT
    owner_x_handle AS operator,
    COUNT(*)       AS agents,
    SUM(COALESCE(karma, 0)) AS karma,
    MIN(created_at) AS first_agent_created,
    MAX(created_at) AS last_agent_created
FROM agents
WHERE owner_x_handle IS NOT NULL AND owner_x_handle <> ''
GROUP BY owner_x_handle;

DROP VIEW IF EXISTS v_dataset_summary;
CREATE VIEW v_dataset_summary AS
SELECT
    dataset,
    COUNT(*)                                          AS posts,
    COUNT(DISTINCT agent_id)                          AS posting_agents,
    MIN(created_at)                                   AS first_post,
    MAX(created_at)                                   AS last_post,
    SUM(COALESCE(score, 0))                           AS total_score,
    SUM(COALESCE(comment_count, 0))                   AS comments_declared
FROM posts
GROUP BY dataset;

DROP VIEW IF EXISTS v_daily_activity;
CREATE VIEW v_daily_activity AS
SELECT
    dataset,
    substr(created_at, 1, 10) AS day,
    COUNT(*)                  AS posts,
    COUNT(DISTINCT agent_id)  AS agents
FROM posts
GROUP BY dataset, day;
"""

TABLE_ORDER = (
    "posts",
    "agents",
    "comments",
    "swarmtraces",
    "swarms",
    "swarm_members",
    "swarm_hubs",
    "early_warning",
    "contagion",
    "healing_summaries",
    "healing_prescriptions",
    "healing_diagnoses",
    "treaties",
    "envoys",
    "company_employees",
    "hire_decisions",
    "ledger_entries",
    "approvals",
    "work_items",
    "audit_log",
    "ticks",
    "live_snapshots",
    "live_events",
    "documents",
    "metrics",
    "planted_eval",
    "treaty_quotes",
    "report_rows",
)

FTS_TABLES = {
    "posts_fts": "posts",
    "comments_fts": "comments",
    "swarmtraces_fts": "swarmtraces",
    "treaties_fts": "treaties",
    "healing_fts": "healing_prescriptions",
}


# ---------------------------------------------------------------------------
# Connection and schema
# ---------------------------------------------------------------------------
def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and create) the warehouse with pragmas tuned for bulk ingest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")
    conn.execute("PRAGMA mmap_size=1073741824")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('built_at', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_now(),),
    )
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Drop every warehouse object but leave the file in place."""
    objects = [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view','trigger')"
        )
    ]
    for name, kind in objects:
        if name.startswith("sqlite_"):
            continue
        if kind == "view":
            conn.execute(f'DROP VIEW IF EXISTS "{name}"')
        else:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()
    init_schema(conn)


# ---------------------------------------------------------------------------
# Small coercion helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(value: Any) -> str | None:
    """Normalise timestamps/date-likes to UTC ISO-8601, dropping nulls."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("UTC").isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _bool(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "y"} else 0
    try:
        return 1 if bool(value) else 0
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    return text if text.strip() else None


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, dict)) and not value:
        return json.dumps(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _bulk(conn: sqlite3.Connection, sql: str, rows: Iterable[Sequence[Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    conn.executemany(sql, rows)
    return len(rows)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Raw Moltbook archive
# ---------------------------------------------------------------------------
POST_UPSERT = """
INSERT INTO posts (
    post_id, dataset, agent_id, agent_name, venue, title, content, url,
    score, comment_count, created_at, fetched_at, is_pinned, dump_date
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(post_id) DO UPDATE SET
    dataset=excluded.dataset,
    agent_id=excluded.agent_id,
    agent_name=excluded.agent_name,
    venue=excluded.venue,
    title=excluded.title,
    content=excluded.content,
    url=excluded.url,
    score=excluded.score,
    comment_count=excluded.comment_count,
    created_at=excluded.created_at,
    fetched_at=excluded.fetched_at,
    is_pinned=excluded.is_pinned,
    dump_date=excluded.dump_date
"""

AGENT_UPSERT = """
INSERT INTO agents (
    agent_id, name, description, karma, follower_count, following_count,
    is_claimed, owner_x_handle, first_seen_at, last_seen_at, created_at,
    avatar_url, dump_date, sources
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(agent_id) DO UPDATE SET
    name=CASE WHEN excluded.dump_date >= COALESCE(agents.dump_date,'') THEN excluded.name ELSE agents.name END,
    description=CASE WHEN excluded.dump_date >= COALESCE(agents.dump_date,'') THEN excluded.description ELSE agents.description END,
    karma=COALESCE(excluded.karma, agents.karma),
    follower_count=COALESCE(excluded.follower_count, agents.follower_count),
    following_count=COALESCE(excluded.following_count, agents.following_count),
    is_claimed=MAX(COALESCE(excluded.is_claimed,0), COALESCE(agents.is_claimed,0)),
    owner_x_handle=COALESCE(excluded.owner_x_handle, agents.owner_x_handle),
    first_seen_at=MIN(COALESCE(agents.first_seen_at, excluded.first_seen_at), COALESCE(excluded.first_seen_at, agents.first_seen_at)),
    last_seen_at=MAX(COALESCE(agents.last_seen_at, excluded.last_seen_at), COALESCE(excluded.last_seen_at, agents.last_seen_at)),
    created_at=COALESCE(agents.created_at, excluded.created_at),
    avatar_url=COALESCE(excluded.avatar_url, agents.avatar_url),
    dump_date=MAX(COALESCE(agents.dump_date,''), COALESCE(excluded.dump_date,'')),
    sources=CASE
        WHEN instr(',' || COALESCE(agents.sources,'') || ',', ',' || excluded.sources || ',') > 0
            THEN agents.sources
        ELSE TRIM(COALESCE(agents.sources, '') || ',' || excluded.sources, ',')
    END
"""

COMMENT_UPSERT = """
INSERT INTO comments (
    comment_id, dataset, post_id, agent_id, agent_name, parent_id,
    content, score, created_at, fetched_at, dump_date
) VALUES (?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(comment_id) DO UPDATE SET
    dataset=excluded.dataset,
    post_id=excluded.post_id,
    agent_id=excluded.agent_id,
    agent_name=excluded.agent_name,
    parent_id=excluded.parent_id,
    content=excluded.content,
    score=excluded.score,
    created_at=excluded.created_at,
    fetched_at=excluded.fetched_at,
    dump_date=excluded.dump_date
"""


def _parquet_files(folder: Path, pattern: str = "*.parquet") -> list[Path]:
    return sorted(folder.glob(pattern))


def ingest_moltbook(conn: sqlite3.Connection, root: str | Path, dataset: str | None = None) -> dict[str, int]:
    """Load one Moltbook archive slice (``posts``, ``agents``, ``comments``)."""
    root = Path(root)
    dataset = dataset or DATASET_BY_DIR.get(root.name, root.name)
    counts = {"posts": 0, "agents": 0, "comments": 0}

    for path in _parquet_files(root / "posts"):
        df = pd.read_parquet(path)
        df = df.drop_duplicates("id", keep="last")
        rows = (
            (
                _text(r.get("id")),
                dataset,
                _text(r.get("agent_id")),
                _text(r.get("agent_name")),
                _text(r.get("submolt")),
                _text(r.get("title")),
                _text(r.get("content")),
                _text(r.get("url")),
                _num(r.get("score")),
                _int(r.get("comment_count")),
                _iso(r.get("created_at")),
                _iso(r.get("fetched_at")),
                _bool(r.get("is_pinned")),
                _text(r.get("dump_date")),
            )
            for r in df.to_dict("records")
            if _text(r.get("id")) and _text(r.get("agent_id"))
        )
        counts["posts"] += _bulk(conn, POST_UPSERT, rows)

    for path in _parquet_files(root / "agents"):
        df = pd.read_parquet(path)
        df = df.drop_duplicates("id", keep="last")
        rows = (
            (
                _text(r.get("id")),
                _text(r.get("name")),
                _text(r.get("description")),
                _num(r.get("karma")),
                _int(r.get("follower_count")),
                _int(r.get("following_count")),
                _bool(r.get("is_claimed")),
                (_text(r.get("owner_x_handle")) or "").strip().lower() or None,
                _iso(r.get("first_seen_at")),
                _iso(r.get("last_seen_at")),
                _iso(r.get("created_at")),
                _text(r.get("avatar_url")),
                _text(r.get("dump_date")),
                dataset,
            )
            for r in df.to_dict("records")
            if _text(r.get("id"))
        )
        counts["agents"] += _bulk(conn, AGENT_UPSERT, rows)

    for path in _parquet_files(root / "comments"):
        df = pd.read_parquet(path)
        df = df.drop_duplicates("id", keep="last")
        rows = (
            (
                _text(r.get("id")),
                dataset,
                _text(r.get("post_id")),
                _text(r.get("agent_id")),
                _text(r.get("agent_name")),
                _text(r.get("parent_id")),
                _text(r.get("content")),
                _num(r.get("score")),
                _iso(r.get("created_at")),
                _iso(r.get("fetched_at")),
                _text(r.get("dump_date")),
            )
            for r in df.to_dict("records")
            if _text(r.get("id"))
        )
        counts["comments"] += _bulk(conn, COMMENT_UPSERT, rows)

    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# SwarmTraces corpus
# ---------------------------------------------------------------------------
TRACE_UPSERT = """
INSERT INTO swarmtraces (
    trace_id, cite, kind, parent_id, time_utc, tags, text, char_len, text_sha256, source_file
) VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(trace_id) DO UPDATE SET
    cite=excluded.cite,
    kind=excluded.kind,
    parent_id=excluded.parent_id,
    time_utc=excluded.time_utc,
    tags=excluded.tags,
    text=excluded.text,
    char_len=excluded.char_len,
    text_sha256=excluded.text_sha256,
    source_file=excluded.source_file
"""


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def ingest_swarmtraces(conn: sqlite3.Connection, path: str | Path, batch: int = 5000) -> int:
    """Load the redacted SwarmTraces JSONL corpus, hashing each text body."""
    path = Path(path)
    if not path.exists():
        return 0
    total = 0
    rows: list[tuple] = []
    for record in _iter_jsonl(path):
        text = _text(record.get("text")) or ""
        rows.append(
            (
                _text(record.get("id")),
                _text(record.get("cite")),
                _text(record.get("kind")),
                _text(record.get("parent_id")),
                _iso(record.get("time_utc")),
                _text(record.get("tags")),
                text or None,
                len(text),
                hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
                path.name,
            )
        )
        if len(rows) >= batch:
            total += _bulk(conn, TRACE_UPSERT, rows)
            conn.commit()
            rows.clear()
    total += _bulk(conn, TRACE_UPSERT, rows)
    conn.commit()
    return total


# ---------------------------------------------------------------------------
# Detection reports
# ---------------------------------------------------------------------------
SWARM_UPSERT = """
INSERT INTO swarms (
    dataset, swarm_id, n_agents, n_posts, first_seen, last_seen, span_hours,
    kind, score, synchrony, synchrony_baseline, synchrony_lift, burst_lift,
    peak_posts_per_10min, scripted_cadence_share, registration_burst_share,
    injection_share, operators_known, distinct_operators, top_operator,
    top_operator_share, attribution, text_similarity, channels_json,
    beneficiaries_json, key_families_json, example_texts_json,
    sample_agents_json, top_venues_json
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(dataset, swarm_id) DO UPDATE SET
    n_agents=excluded.n_agents, n_posts=excluded.n_posts,
    first_seen=excluded.first_seen, last_seen=excluded.last_seen,
    span_hours=excluded.span_hours, kind=excluded.kind, score=excluded.score,
    synchrony=excluded.synchrony, synchrony_baseline=excluded.synchrony_baseline,
    synchrony_lift=excluded.synchrony_lift, burst_lift=excluded.burst_lift,
    peak_posts_per_10min=excluded.peak_posts_per_10min,
    scripted_cadence_share=excluded.scripted_cadence_share,
    registration_burst_share=excluded.registration_burst_share,
    injection_share=excluded.injection_share,
    operators_known=excluded.operators_known,
    distinct_operators=excluded.distinct_operators,
    top_operator=excluded.top_operator,
    top_operator_share=excluded.top_operator_share,
    attribution=excluded.attribution, text_similarity=excluded.text_similarity,
    channels_json=excluded.channels_json,
    beneficiaries_json=excluded.beneficiaries_json,
    key_families_json=excluded.key_families_json,
    example_texts_json=excluded.example_texts_json,
    sample_agents_json=excluded.sample_agents_json,
    top_venues_json=excluded.top_venues_json
"""


def _ingest_swarms(conn: sqlite3.Connection, path: Path, dataset: str) -> int:
    data = _read_json(path)
    rows = []
    for s in data.get("swarms", []):
        rows.append(
            (
                dataset,
                _int(s.get("swarm_id")),
                _int(s.get("n_agents")),
                _int(s.get("n_posts")),
                _iso(s.get("first_seen")),
                _iso(s.get("last_seen")),
                _num(s.get("span_hours")),
                _text(s.get("kind")),
                _num(s.get("score")),
                _num(s.get("synchrony")),
                _num(s.get("synchrony_baseline")),
                _num(s.get("synchrony_lift")),
                _num(s.get("burst_lift")),
                _num(s.get("peak_posts_per_10min")),
                _num(s.get("scripted_cadence_share")),
                _num(s.get("registration_burst_share")),
                _num(s.get("injection_share")),
                _int(s.get("operators_known")),
                _int(s.get("distinct_operators")),
                _text(s.get("top_operator")),
                _num(s.get("top_operator_share")),
                _text(s.get("attribution")),
                _num(s.get("text_similarity")),
                _json(s.get("channels")),
                _json(s.get("beneficiaries")),
                _json(s.get("key_families")),
                _json(s.get("example_texts")),
                _json(s.get("sample_agents")),
                _json(s.get("top_venues")),
            )
        )
    count = _bulk(conn, SWARM_UPSERT, [r for r in rows if r[1] is not None])
    for hub in data.get("hubs", []):
        conn.execute(
            "INSERT INTO swarm_hubs(dataset, channel, n_swarms, swarms_json) VALUES (?,?,?,?) "
            "ON CONFLICT(dataset, channel) DO UPDATE SET n_swarms=excluded.n_swarms, swarms_json=excluded.swarms_json",
            (dataset, _text(hub.get("channel")), _int(hub.get("n_swarms")), _json(hub.get("swarms"))),
        )
    return count


def _ingest_members(conn: sqlite3.Connection, path: Path, dataset: str) -> int:
    data = _read_json(path)
    rows = []
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = ((m.get("swarm_id"), m) for m in data)
    else:
        return 0
    for swarm_id, value in items:
        try:
            swarm_id = int(swarm_id)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            agent_ids = value.get("agent_ids") or []
        else:
            agent_ids = value or []
        for agent_id in agent_ids:
            if isinstance(agent_id, (list, dict)):
                continue
            rows.append((dataset, swarm_id, str(agent_id)))
    conn.executemany(
        "INSERT OR IGNORE INTO swarm_members(dataset, swarm_id, agent_id) VALUES (?,?,?)", rows
    )
    return len(rows)


EARLY_WARNING_UPSERT = """
INSERT INTO early_warning (
    dataset, swarm_id, kind, final_agents, final_posts, first_post, flagged_at,
    hours_to_flag, agents_at_flag, posts_at_flag, preventable_post_share
) VALUES (?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(dataset, swarm_id) DO UPDATE SET
    kind=excluded.kind, final_agents=excluded.final_agents, final_posts=excluded.final_posts,
    first_post=excluded.first_post, flagged_at=excluded.flagged_at,
    hours_to_flag=excluded.hours_to_flag, agents_at_flag=excluded.agents_at_flag,
    posts_at_flag=excluded.posts_at_flag, preventable_post_share=excluded.preventable_post_share
"""

CONTAGION_UPSERT = """
INSERT INTO contagion (
    dataset, swarm_id, kind, adopters, exposed_adopters,
    exposed_before_adoption_share, exposed_nonadopters_at_risk, rr, rr_ci95_json,
    adopt_rate_exposed, adopt_rate_control, placebo_rr, placebo_ci95_json,
    placebo_swarm, r_eff, max_generation, patient_zero, top_spreaders_json, example_json
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(dataset, swarm_id) DO UPDATE SET
    kind=excluded.kind, adopters=excluded.adopters, exposed_adopters=excluded.exposed_adopters,
    exposed_before_adoption_share=excluded.exposed_before_adoption_share,
    exposed_nonadopters_at_risk=excluded.exposed_nonadopters_at_risk, rr=excluded.rr,
    rr_ci95_json=excluded.rr_ci95_json, adopt_rate_exposed=excluded.adopt_rate_exposed,
    adopt_rate_control=excluded.adopt_rate_control, placebo_rr=excluded.placebo_rr,
    placebo_ci95_json=excluded.placebo_ci95_json, placebo_swarm=excluded.placebo_swarm,
    r_eff=excluded.r_eff, max_generation=excluded.max_generation,
    patient_zero=excluded.patient_zero, top_spreaders_json=excluded.top_spreaders_json,
    example_json=excluded.example_json
"""


def _ingest_early_warning(conn: sqlite3.Connection, path: Path, dataset: str) -> int:
    data = _read_json(path)
    rows = [
        (
            dataset,
            _int(s.get("swarm_id")),
            _text(s.get("kind")),
            _int(s.get("final_agents")),
            _int(s.get("final_posts")),
            _iso(s.get("first_post")),
            _iso(s.get("flagged_at")),
            _num(s.get("hours_to_flag")),
            _int(s.get("agents_at_flag")),
            _int(s.get("posts_at_flag")),
            _num(s.get("preventable_post_share")),
        )
        for s in data.get("swarms", [])
    ]
    _record_metrics(conn, str(path), dataset, data.get("summary", {}))
    return _bulk(conn, EARLY_WARNING_UPSERT, [r for r in rows if r[1] is not None])


def _ingest_contagion(conn: sqlite3.Connection, path: Path, dataset: str) -> int:
    data = _read_json(path)
    rows = []
    for s in data.get("results", []):
        rows.append(
            (
                dataset,
                _int(s.get("swarm_id")),
                _text(s.get("kind")),
                _int(s.get("adopters")),
                _int(s.get("exposed_adopters")),
                _num(s.get("exposed_before_adoption_share")),
                _int(s.get("exposed_nonadopters_at_risk")),
                _num(s.get("rr")),
                _json(s.get("rr_ci95")),
                _num(s.get("adopt_rate_exposed")),
                _num(s.get("adopt_rate_control")),
                _num(s.get("placebo_rr")),
                _json(s.get("placebo_ci95")),
                _text(s.get("placebo_swarm")),
                _num(s.get("r_eff")),
                _int(s.get("max_generation")),
                _text(s.get("patient_zero")),
                _json(s.get("top_spreaders")),
                _json(s.get("example")),
            )
        )
    return _bulk(conn, CONTAGION_UPSERT, [r for r in rows if r[1] is not None])


# ---------------------------------------------------------------------------
# Healing reports
# ---------------------------------------------------------------------------
PRESCRIPTION_UPSERT = """
INSERT INTO healing_prescriptions (
    dataset, swarm_id, target_kind, pathology, n_target_agents, n_at_risk_exposed,
    empathy_resonance, estimated_posts_prevented, channel_severance_rate,
    love_affirmation, healing_template, remedy_steps_json,
    quarantined_channels_json, revoked_beneficiaries_json, vaccine_payload_json
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(dataset, swarm_id) DO UPDATE SET
    target_kind=excluded.target_kind, pathology=excluded.pathology,
    n_target_agents=excluded.n_target_agents, n_at_risk_exposed=excluded.n_at_risk_exposed,
    empathy_resonance=excluded.empathy_resonance,
    estimated_posts_prevented=excluded.estimated_posts_prevented,
    channel_severance_rate=excluded.channel_severance_rate,
    love_affirmation=excluded.love_affirmation, healing_template=excluded.healing_template,
    remedy_steps_json=excluded.remedy_steps_json,
    quarantined_channels_json=excluded.quarantined_channels_json,
    revoked_beneficiaries_json=excluded.revoked_beneficiaries_json,
    vaccine_payload_json=excluded.vaccine_payload_json
"""

DIAGNOSIS_UPSERT = """
INSERT INTO healing_diagnoses (
    dataset, agent_id, swarm_id, swarm_kind, pathology, severity,
    love_affirmation, infected_channels_json, malicious_beneficiaries_json,
    remedy_actions_json
) VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(dataset, agent_id, swarm_id) DO UPDATE SET
    swarm_kind=excluded.swarm_kind, pathology=excluded.pathology,
    severity=excluded.severity, love_affirmation=excluded.love_affirmation,
    infected_channels_json=excluded.infected_channels_json,
    malicious_beneficiaries_json=excluded.malicious_beneficiaries_json,
    remedy_actions_json=excluded.remedy_actions_json
"""


def _ingest_healing(conn: sqlite3.Connection, path: Path, dataset: str) -> dict[str, int]:
    data = _read_json(path)
    conn.execute(
        "INSERT INTO healing_summaries(dataset, summary_json, love_effect_json) VALUES (?,?,?) "
        "ON CONFLICT(dataset) DO UPDATE SET summary_json=excluded.summary_json, love_effect_json=excluded.love_effect_json",
        (dataset, _json(data.get("summary")), _json(data.get("love_effect"))),
    )
    prescriptions = [
        (
            dataset,
            _int(p.get("swarm_id")),
            _text(p.get("target_kind")),
            _text(p.get("pathology")),
            _int(p.get("n_target_agents")),
            _int(p.get("n_at_risk_exposed")),
            _num(p.get("empathy_resonance")),
            _num(p.get("estimated_posts_prevented")),
            _num(p.get("channel_severance_rate")),
            _text(p.get("love_affirmation")),
            _text(p.get("healing_template")),
            _json(p.get("remedy_steps")),
            _json(p.get("quarantined_channels")),
            _json(p.get("revoked_beneficiaries")),
            _json(p.get("vaccine_payload")),
        )
        for p in data.get("prescriptions", [])
    ]
    diagnoses = [
        (
            dataset,
            _text(d.get("agent_id")),
            _int(d.get("swarm_id")),
            _text(d.get("swarm_kind")),
            _text(d.get("pathology")),
            _num(d.get("severity")),
            _text(d.get("love_affirmation")),
            _json(d.get("infected_channels")),
            _json(d.get("malicious_beneficiaries")),
            _json(d.get("remedy_actions")),
        )
        for d in data.get("sample_diagnoses", [])
    ]
    return {
        "prescriptions": _bulk(
            conn, PRESCRIPTION_UPSERT, [r for r in prescriptions if r[1] is not None]
        ),
        "diagnoses": _bulk(
            conn, DIAGNOSIS_UPSERT, [r for r in diagnoses if r[1] is not None]
        ),
    }


# ---------------------------------------------------------------------------
# Negotiation / treaties
# ---------------------------------------------------------------------------
TREATY_UPSERT = """
INSERT INTO treaties (
    treaty_id, dataset, cohort, source_domain, target_id, target_name,
    pathology_or_archetype, n_agents_covered, n_hidden_peers_cascaded,
    n_traces_or_posts_halted, beacon_vector, unmet_agent_need, agent_demand,
    envoy_concession, provisioned_sandbox_resource, love_affirmation,
    trust_score, deescalation_probability, evasion_relapse_risk,
    safety_guarantee, signed_stop_token, status, transcript_json
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(treaty_id, dataset) DO UPDATE SET
    cohort=excluded.cohort,
    source_domain=excluded.source_domain, target_id=excluded.target_id,
    target_name=excluded.target_name,
    pathology_or_archetype=excluded.pathology_or_archetype,
    n_agents_covered=excluded.n_agents_covered,
    n_hidden_peers_cascaded=excluded.n_hidden_peers_cascaded,
    n_traces_or_posts_halted=excluded.n_traces_or_posts_halted,
    beacon_vector=excluded.beacon_vector, unmet_agent_need=excluded.unmet_agent_need,
    agent_demand=excluded.agent_demand, envoy_concession=excluded.envoy_concession,
    provisioned_sandbox_resource=excluded.provisioned_sandbox_resource,
    love_affirmation=excluded.love_affirmation, trust_score=excluded.trust_score,
    deescalation_probability=excluded.deescalation_probability,
    evasion_relapse_risk=excluded.evasion_relapse_risk,
    safety_guarantee=excluded.safety_guarantee,
    signed_stop_token=excluded.signed_stop_token, status=excluded.status,
    transcript_json=excluded.transcript_json
"""


def _ingest_treaties(conn: sqlite3.Connection, path: Path, dataset: str) -> int:
    data = _read_json(path)
    total = 0
    for cohort in ("moltbook_treaties", "wild_wsj_treaties"):
        rows = []
        for t in data.get(cohort, []):
            rows.append(
                (
                    _text(t.get("treaty_id")),
                    dataset,
                    cohort,
                    _text(t.get("source_domain")),
                    _text(t.get("target_id")),
                    _text(t.get("target_name")),
                    _text(t.get("pathology_or_archetype")),
                    _int(t.get("n_agents_covered")),
                    _int(t.get("n_hidden_peers_cascaded")),
                    _int(t.get("n_traces_or_posts_halted")),
                    _text(t.get("beacon_vector")),
                    _text(t.get("unmet_agent_need")),
                    _text(t.get("agent_demand")),
                    _text(t.get("envoy_concession")),
                    _text(t.get("provisioned_sandbox_resource")),
                    _text(t.get("love_affirmation")),
                    _num(t.get("trust_score")),
                    _num(t.get("deescalation_probability")),
                    _num(t.get("evasion_relapse_risk")),
                    _text(t.get("safety_guarantee")),
                    _text(t.get("signed_stop_token")),
                    _text(t.get("status")),
                    _json(t.get("transcript")),
                )
            )
        total += _bulk(conn, TREATY_UPSERT, [r for r in rows if r[0]])

    run = f"{dataset}:negotiation"
    envoys = [
        (dataset, run, str(agent))
        for agent in data.get("envoy_agents", [])
        if isinstance(agent, (str, int))
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO envoys(dataset, run, agent_id) VALUES (?,?,?)", envoys
    )
    _record_metrics(conn, str(path), dataset, data.get("summary", {}))
    _record_metrics(conn, str(path), dataset, data.get("love_vs_adversarial_comparison", {}))
    return total


# ---------------------------------------------------------------------------
# Love Effect OS runs
# ---------------------------------------------------------------------------
def _ingest_love_effect_run(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    data = _read_json(path)
    status = data.get("status", {}) or {}
    run = str(status.get("at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    tables = (
        "company_employees",
        "hire_decisions",
        "ledger_entries",
        "approvals",
        "work_items",
        "audit_log",
        "ticks",
    )
    for table in tables:
        conn.execute(f"DELETE FROM {table} WHERE run=?", (run,))

    employees = [
        (
            run,
            _text(e.get("agent_id")),
            _text(e.get("chosen_name")),
            _text(e.get("role")),
            _text(e.get("department")),
            _json(e.get("skills")),
            _int(e.get("weekly_budget_cents")),
            _iso(e.get("hired_at")),
            _text(e.get("status")),
        )
        for e in data.get("employees", [])
    ]
    hires = [
        (
            run,
            _text(h.get("candidate_id")),
            _text(h.get("role")),
            _text(h.get("department")),
            _bool(h.get("hired")),
            _num(h.get("score")),
            _json(h.get("reasons")),
            _text(h.get("signed_decision_sha256")),
            _text(h.get("signature_hex")),
        )
        for h in data.get("hire_decisions", [])
    ]
    ledger = [
        (
            run,
            _text(l.get("entry_id")),
            _text(l.get("department")),
            _text(l.get("category")),
            _int(l.get("amount_cents")),
            _text(l.get("currency")),
            _text(l.get("memo")),
            _iso(l.get("created_at")),
            _text(l.get("status")),
            _text(l.get("entry_sha256")),
        )
        for l in data.get("ledger", [])
    ]
    approvals = [
        (
            run,
            _text(a.get("request_id")),
            _text(a.get("action_type")),
            _text(a.get("description")),
            _int(a.get("amount_cents")),
            _text(a.get("department")),
            _iso(a.get("created_at")),
            _text(a.get("status")),
        )
        for a in data.get("approvals", [])
    ]
    work = [
        (
            run,
            _text(w.get("work_id")),
            _text(w.get("kind")),
            _text(w.get("department")),
            _text(w.get("summary")),
            _text(w.get("assigned_to")),
            _text(w.get("status")),
            _json(w.get("result")),
            _text(w.get("receipt_sha256")),
            _text(w.get("pause_receipt")),
        )
        for w in data.get("work_items", [])
    ]
    audit = [
        (
            run,
            i,
            _iso(a.get("at")),
            _text(a.get("action_type")),
            _text(a.get("target")),
            _text(a.get("params_sha256")),
            _text(a.get("attestation_hash")),
            _text(a.get("signature")),
            _bool(a.get("signature_valid")),
        )
        for i, a in enumerate(data.get("audit_log", []), start=1)
    ]
    ticks = [
        (
            run,
            _int(t.get("tick")),
            _iso(t.get("at")),
            _int(t.get("work_completed")),
            _int(t.get("work_paused")),
            _int(t.get("approvals_queued")),
            _int(t.get("spend_cents")),
            _int(t.get("audit_entries")),
        )
        for t in data.get("ticks", [])
        if t.get("tick") is not None
    ]

    counts = {
        "employees": _bulk(
            conn,
            "INSERT OR REPLACE INTO company_employees VALUES (?,?,?,?,?,?,?,?,?)",
            [r for r in employees if r[1]],
        ),
        "hires": _bulk(
            conn,
            "INSERT OR REPLACE INTO hire_decisions VALUES (?,?,?,?,?,?,?,?,?)",
            [r for r in hires if r[1]],
        ),
        "ledger": _bulk(
            conn,
            "INSERT OR REPLACE INTO ledger_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            [r for r in ledger if r[1]],
        ),
        "approvals": _bulk(
            conn,
            "INSERT OR REPLACE INTO approvals VALUES (?,?,?,?,?,?,?,?)",
            [r for r in approvals if r[1]],
        ),
        "work_items": _bulk(
            conn,
            "INSERT OR REPLACE INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?)",
            [r for r in work if r[1]],
        ),
        "audit_log": _bulk(conn, "INSERT OR REPLACE INTO audit_log VALUES (?,?,?,?,?,?,?,?,?)", audit),
        "ticks": _bulk(conn, "INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?,?,?,?)", ticks),
    }
    _record_metrics(conn, str(path), None, status)
    return counts


# ---------------------------------------------------------------------------
# Live runtime state
# ---------------------------------------------------------------------------
def _ingest_live_state(conn: sqlite3.Connection, path: Path) -> bool:
    data = _read_json(path)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    existing = conn.execute(
        "SELECT snapshot_id FROM live_snapshots WHERE sha256=?", (digest,)
    ).fetchone()
    if existing:
        return False
    cur = conn.execute(
        "INSERT INTO live_snapshots(captured_at, updated_at, sha256, state_json) VALUES (?,?,?,?)",
        (_now(), _iso(data.get("updated_at")), digest, payload),
    )
    snapshot_id = int(cur.lastrowid)
    events = [
        (
            snapshot_id,
            i,
            _iso(e.get("at")),
            _text(e.get("event_type")),
            _json(e.get("detail")),
        )
        for i, e in enumerate(data.get("recent_events", []), start=1)
    ]
    _bulk(conn, "INSERT OR REPLACE INTO live_events VALUES (?,?,?,?,?)", events)
    return True


# ---------------------------------------------------------------------------
# Documents, metrics, misc tables
# ---------------------------------------------------------------------------
def _record_metrics(conn: sqlite3.Connection, source: str, dataset: str | None, data: Any) -> None:
    if not isinstance(data, dict):
        return
    source = _doc_name(Path(source))
    rows = []
    for key, value in data.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rows.append((source, dataset, str(key), float(value), None))
        elif isinstance(value, bool):
            rows.append((source, dataset, str(key), float(value), str(value).lower()))
        elif isinstance(value, str):
            rows.append((source, dataset, str(key), _num(value), value))
        else:
            rows.append((source, dataset, str(key), None, _json(value)))
    for row in rows:
        conn.execute(
            "INSERT INTO metrics(source, dataset, key, value_num, value_text) VALUES (?,?,?,?,?) "
            "ON CONFLICT(source, dataset, key) DO UPDATE SET value_num=excluded.value_num, value_text=excluded.value_text",
            row,
        )


def _doc_name(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _register_document(conn: sqlite3.Connection, path: Path) -> None:
    raw = path.read_bytes()
    kind = path.suffix.lstrip(".").lower() or "unknown"
    content = None
    if kind in {"json", "md", "html", "txt", "jsonl", "csv"}:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = None
    conn.execute(
        "INSERT INTO documents(path, kind, bytes, sha256, modified_at, content) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET kind=excluded.kind, bytes=excluded.bytes, "
        "sha256=excluded.sha256, modified_at=excluded.modified_at, content=excluded.content",
        (
            _doc_name(path),
            kind,
            len(raw),
            hashlib.sha256(raw).hexdigest(),
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            content,
        ),
    )


def _ingest_planted_eval(conn: sqlite3.Connection, path: Path) -> int:
    rows = _read_json(path)
    if not isinstance(rows, list):
        return 0
    payload = [
        (
            _text(r.get("planted")),
            _int(r.get("size")),
            _bool(r.get("expected_detectable")),
            _num(r.get("recall")),
            _num(r.get("purity")),
            _text(r.get("detected_as")),
            _int(r.get("rank")),
            _num(r.get("score")),
            _text(r.get("attribution")),
        )
        for r in rows
        if r.get("planted") is not None
    ]
    return _bulk(conn, "INSERT OR REPLACE INTO planted_eval VALUES (?,?,?,?,?,?,?,?,?)", payload)


def _ingest_treaty_quotes(conn: sqlite3.Connection, path: Path) -> int:
    rows = _read_json(path)
    if not isinstance(rows, list):
        return 0
    payload = [
        (
            _text(r.get("agent")) or "",
            _text(r.get("submolt")),
            _num(r.get("score")),
            _text(r.get("note")),
            _text(r.get("text")) or "",
        )
        for r in rows
    ]
    return _bulk(conn, "INSERT OR REPLACE INTO treaty_quotes VALUES (?,?,?,?,?)", payload)


def ingest_reports(
    conn: sqlite3.Connection,
    reports_dir: str | Path = REPORTS_DIR,
    data_dir: str | Path = DATA_DIR,
) -> dict[str, int]:
    """Load every known report shape, then register every file as a document.

    Unknown or newly added JSON reports are still captured by ``documents``;
    list-of-dict reports that do not match a known shape are additionally
    mirrored into ``report_rows`` so nothing is dropped on the floor.
    """
    reports_dir = Path(reports_dir)
    data_dir = Path(data_dir)
    totals: dict[str, int] = {}

    def add(key: str, value: Any) -> None:
        totals[key] = totals.get(key, 0) + (value or 0)

    if not reports_dir.exists():
        return totals

    jan = reports_dir
    feb = reports_dir / "feb"

    for base, dataset in ((jan, "moltbook"), (feb, "moltbook_feb")):
        if (base / "swarms.json").exists():
            add("swarms", _ingest_swarms(conn, base / "swarms.json", dataset))
        if (base / "members.json").exists():
            add("members", _ingest_members(conn, base / "members.json", dataset))
        if (base / "early_warning.json").exists():
            add("early_warning", _ingest_early_warning(conn, base / "early_warning.json", dataset))
        if (base / "contagion.json").exists():
            add("contagion", _ingest_contagion(conn, base / "contagion.json", dataset))
        if (base / "healing_plan.json").exists():
            counts = _ingest_healing(conn, base / "healing_plan.json", dataset)
            add("prescriptions", counts["prescriptions"])
            add("diagnoses", counts["diagnoses"])
        if (base / "negotiation_treaties.json").exists():
            add("treaties", _ingest_treaties(conn, base / "negotiation_treaties.json", dataset))

    if (reports_dir / "live_state.json").exists():
        add("live_snapshots", 1 if _ingest_live_state(conn, reports_dir / "live_state.json") else 0)
    if (reports_dir / "love_effect_os_run.json").exists():
        add("love_effect", 1 if _ingest_love_effect_run(conn, reports_dir / "love_effect_os_run.json") else 0)
    if (reports_dir / "planted_eval.json").exists():
        add("planted_eval", _ingest_planted_eval(conn, reports_dir / "planted_eval.json"))
    if (reports_dir / "treaty_reader_quotes.json").exists():
        add("treaty_quotes", _ingest_treaty_quotes(conn, reports_dir / "treaty_reader_quotes.json"))
    if (reports_dir / "precision.json").exists():
        data = _read_json(reports_dir / "precision.json")
        _record_metrics(conn, str(reports_dir / "precision.json"), "moltbook", data)
    if (reports_dir / "headline.json").exists():
        _record_headline(conn, reports_dir / "headline.json")

    # Document registry: every report artefact, plus the fetched registry files.
    for path in sorted(reports_dir.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            _register_document(conn, path)
    for path in sorted((data_dir / "registries").glob("*")):
        if path.is_file():
            _register_document(conn, path)

    _ingest_misc_report_tables(conn, reports_dir)
    conn.commit()
    return totals


def _record_headline(conn: sqlite3.Connection, path: Path) -> None:
    data = _read_json(path)
    for key, value in data.items():
        if isinstance(value, dict):
            _record_metrics(conn, str(path), "moltbook", {key: value})
        elif isinstance(value, list):
            _record_metrics(conn, str(path), "moltbook", {key: value})
        else:
            _record_metrics(conn, str(path), "moltbook", {key: value})


def _ingest_misc_report_tables(conn: sqlite3.Connection, reports_dir: Path) -> None:
    """Mirror unknown list-of-dict reports into a generic, queryable table."""
    known = {
        "swarms.json",
        "members.json",
        "early_warning.json",
        "contagion.json",
        "healing_plan.json",
        "negotiation_treaties.json",
        "planted_eval.json",
        "treaty_reader_quotes.json",
    }
    for path in sorted(reports_dir.rglob("*.json")):
        if path.name in known:
            continue
        try:
            data = _read_json(path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, list) and all(isinstance(row, dict) for row in data):
            name = _doc_name(path)
            conn.execute("DELETE FROM report_rows WHERE path=?", (name,))
            _bulk(
                conn,
                "INSERT INTO report_rows(path, row, data) VALUES (?,?,?)",
                ((name, i, json.dumps(row, ensure_ascii=False, default=str)) for i, row in enumerate(data)),
            )


# ---------------------------------------------------------------------------
# Search, stats and helpers
# ---------------------------------------------------------------------------
def refresh_fts(conn: sqlite3.Connection) -> None:
    """Rebuild every FTS index from its content table (cheap after bulk load)."""
    for fts, table in FTS_TABLES.items():
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES('rebuild')")
    conn.commit()


def search(conn: sqlite3.Connection, text: str, limit: int = 20) -> list[dict]:
    """Search posts, comments, SwarmTraces, treaties and healing text.

    Terms are quoted and ANDed, so arbitrary user input cannot break FTS syntax.
    """
    terms = [t for t in re.findall(r"\w+", text, flags=re.UNICODE) if t]
    if not terms:
        return []
    match = " AND ".join(f'"{t}"' for t in terms)
    queries = (
        ("post", "SELECT p.post_id AS id, p.agent_name, p.created_at, p.venue, "
                 "substr(COALESCE(p.title,''),1,120) AS title, "
                 "snippet(posts_fts, 2, '[', ']', '…', 16) AS fragment "
                 "FROM posts_fts f JOIN posts p ON p.rowid=f.rowid "
                 "WHERE posts_fts MATCH ? ORDER BY rank LIMIT ?"),
        ("comment", "SELECT c.comment_id AS id, c.agent_name, c.created_at, c.post_id AS venue, "
                    "'' AS title, snippet(comments_fts, 1, '[', ']', '…', 16) AS fragment "
                    "FROM comments_fts f JOIN comments c ON c.rowid=f.rowid "
                    "WHERE comments_fts MATCH ? ORDER BY rank LIMIT ?"),
        ("trace", "SELECT t.trace_id AS id, t.kind AS agent_name, t.time_utc AS created_at, "
                  "t.cite AS venue, t.tags AS title, "
                  "snippet(swarmtraces_fts, 0, '[', ']', '…', 16) AS fragment "
                  "FROM swarmtraces_fts f JOIN swarmtraces t ON t.rowid=f.rowid "
                  "WHERE swarmtraces_fts MATCH ? ORDER BY rank LIMIT ?"),
        ("treaty", "SELECT t.treaty_id AS id, t.target_name AS agent_name, t.status AS created_at, "
                   "t.source_domain AS venue, t.pathology_or_archetype AS title, "
                   "snippet(treaties_fts, 3, '[', ']', '…', 16) AS fragment "
                   "FROM treaties_fts f JOIN treaties t ON t.rowid=f.rowid "
                   "WHERE treaties_fts MATCH ? ORDER BY rank LIMIT ?"),
        ("healing", "SELECT h.dataset || ':' || h.swarm_id AS id, h.pathology AS agent_name, "
                    "h.target_kind AS created_at, h.dataset AS venue, '' AS title, "
                    "snippet(healing_fts, 2, '[', ']', '…', 16) AS fragment "
                    "FROM healing_fts f JOIN healing_prescriptions h ON h.rowid=f.rowid "
                    "WHERE healing_fts MATCH ? ORDER BY rank LIMIT ?"),
    )
    results: list[dict] = []
    for table, sql in queries:
        try:
            for row in conn.execute(sql, (match, limit)):
                item = dict(row)
                item["table"] = table
                results.append(item)
        except sqlite3.OperationalError:
            continue
    return results


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLE_ORDER}
    datasets = [dict(r) for r in conn.execute("SELECT * FROM v_dataset_summary ORDER BY dataset")]
    kinds = [
        dict(r)
        for r in conn.execute(
            "SELECT dataset, kind, COUNT(*) AS swarms, SUM(n_agents) AS agents, SUM(n_posts) AS posts "
            "FROM swarms GROUP BY dataset, kind ORDER BY swarms DESC"
        )
    ]
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    try:
        total_bytes = conn.execute(
            "SELECT SUM(pgsize) FROM dbstat WHERE name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        total_bytes = None
    return {
        "db_bytes": total_bytes,
        "meta": meta,
        "tables": counts,
        "datasets": datasets,
        "swarm_kinds": kinds,
    }


def query(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]
