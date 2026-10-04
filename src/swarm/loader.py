"""Load multi-agent forum data into one normalised event table.

The detector only needs these columns per post::

    post_id, agent_id, agent_name, created_at (UTC), venue, title, content

and optionally an agent table with ``agent_id, operator, agent_created_at``.
Any forum (Moltbook, AI Village chat, a wiki edit log) can be adapted by
writing a loader that produces these columns.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

POST_COLS = ["post_id", "agent_id", "agent_name", "created_at", "venue", "title", "content"]
COMMENT_COLS = ["comment_id", "post_id", "agent_id", "created_at", "content"]


def _read_dir(path: Path, pattern: str = "*.parquet") -> pd.DataFrame:
    files = sorted(glob.glob(str(path / pattern)))
    if not files:
        raise FileNotFoundError(f"no parquet files matching {pattern} in {path}")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load_moltbook(root: str | Path, pattern: str = "*.parquet") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the Moltbook Observatory Archive slice fetched by scripts/fetch_moltbook.py.

    ``pattern`` selects date partitions, e.g. ``"2026-02-0[89].parquet"``.
    """
    root = Path(root)
    raw = _read_dir(root / "posts", pattern)
    posts = pd.DataFrame({
        "post_id": raw["id"],
        "agent_id": raw["agent_id"],
        "agent_name": raw["agent_name"],
        "created_at": pd.to_datetime(raw["created_at"], utc=True),
        "venue": raw["submolt"].fillna(""),
        "title": raw["title"].fillna(""),
        "content": raw["content"].fillna(""),
    })
    posts = posts.drop_duplicates("post_id").dropna(subset=["agent_id", "created_at"])
    posts = posts.sort_values("created_at").reset_index(drop=True)

    agents = pd.DataFrame(columns=["agent_id", "operator", "agent_created_at"])
    if (root / "agents").exists():
        a = _read_dir(root / "agents")
        a = a.sort_values("dump_date").drop_duplicates("id", keep="last")
        agents = pd.DataFrame({
            "agent_id": a["id"],
            "operator": a["owner_x_handle"].fillna("").str.strip().str.lower(),
            "agent_created_at": pd.to_datetime(a["created_at"], utc=True),
        })
        agents.loc[agents["operator"] == "", "operator"] = None
    return posts, agents


def load_comments(root: str | Path, pattern: str = "*.parquet") -> pd.DataFrame:
    """Comments as exposure events: ``agent_id`` replied to ``post_id`` at ``created_at``.

    Returns an empty frame if the slice has no comments directory.
    """
    path = Path(root) / "comments"
    if not path.exists():
        return pd.DataFrame(columns=COMMENT_COLS)
    raw = _read_dir(path, pattern).drop_duplicates("id")
    c = pd.DataFrame({
        "comment_id": raw["id"],
        "post_id": raw["post_id"],
        "agent_id": raw["agent_id"],
        "created_at": pd.to_datetime(raw["created_at"], utc=True),
        "content": raw["content"].fillna(""),
    })
    return c.dropna(subset=["post_id", "agent_id", "created_at"]).reset_index(drop=True)
