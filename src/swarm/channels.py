"""Upstream channel discovery: what is driving a swarm?

Operator attribution fails on Moltbook because swarms span hundreds of
unrelated owners. What they share instead is an upstream channel: a skill
URL, a token launchpad, a verification service, an account they are told to
follow. For each swarm this module finds channels that are

- over-represented in the swarm's posts against the rest of the corpus
  (one-sided Fisher exact test, Bonferroni over every channel tested), and
- used by at least two distinct owners (a channel inside one operator's
  fleet is ownership, not upstream coordination).

It also reports *lead time*: how long before the swarm's first post the
channel was first seen anywhere, and whether that first sighting came from a
swarm member or an outsider. A channel that appears before the swarm, posted
by a non-member, is a candidate origin. Channels significant in several
swarms are returned as hubs: shared infrastructure behind campaigns that look
unrelated.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd
from scipy.stats import fisher_exact

URL_RE = re.compile(r"https?://[^\s)\]\"'<>`]+", re.I)
MENTION_RE = re.compile(r"(?<![\w/@.])@([A-Za-z0-9_]{3,30})\b")
# The platform itself, plus generic code hosts whose *host* says nothing
# (the repository path is kept, it is the informative part).
IGNORE_HOSTS = {"moltbook.com"}
PATH_ONLY_HOSTS = {"github.com", "gitlab.com", "raw.githubusercontent.com", "gist.github.com",
                   "huggingface.co", "x.com", "twitter.com"}


def extract_channels(text: str) -> set[str]:
    """``dom:<host>``, ``path:<host>/<seg1>/<seg2>`` and ``at:<handle>`` tokens."""
    out: set[str] = set()
    for u in URL_RE.findall(text or ""):
        try:  # agent posts contain malformed URLs (e.g. stray "[" parsed as IPv6)
            p = urlparse(u.rstrip(".,;:!?"))
            host = (p.hostname or "").lower().removeprefix("www.")
        except ValueError:
            continue
        if not host or host in IGNORE_HOSTS:
            continue
        if host not in PATH_ONLY_HOSTS:
            out.add("dom:" + host)
        segs = [s for s in p.path.split("/") if s][:2]
        if segs:
            out.add("path:" + host + "/" + "/".join(s.lower() for s in segs))
    for m in MENTION_RE.findall(text or ""):
        out.add("at:" + m.lower())
    return out


def attach_channels(swarms, posts: pd.DataFrame, agents: pd.DataFrame | None = None,
                    alpha: float = 0.01, min_agents: int = 3, min_operators: int = 2,
                    top: int = 5) -> list[dict]:
    """Annotate each swarm's ``channels`` in place; return hub channels."""
    pid = posts["post_id"].to_numpy()
    chans = [extract_channels(f"{t or ''}\n{c or ''}")
             for t, c in zip(posts["title"].to_numpy(), posts["content"].to_numpy())]
    by_post = dict(zip(pid, chans))
    agent_of = dict(zip(pid, posts["agent_id"].to_numpy()))
    time_of = dict(zip(pid, posts["created_at"]))
    corpus = Counter(ch for cs in chans for ch in cs)
    first_global: dict = {}
    for p, cs in zip(pid, chans):
        for c in cs:
            if c not in first_global or time_of[p] < first_global[c][0]:
                first_global[c] = (time_of[p], agent_of[p])
    n_corpus = len(posts)
    op_of: dict = {}
    if agents is not None and len(agents):
        a = agents.dropna(subset=["operator"]).drop_duplicates("agent_id")
        op_of = dict(zip(a["agent_id"], a["operator"]))

    candidates = []
    for s in swarms:
        k_count = Counter(c for p in s.post_ids for c in by_post.get(p, ()))
        candidates.append(k_count)
    n_tests = max(1, sum(len(k) for k in candidates))

    hubs: dict = defaultdict(list)
    for s, k_count in zip(swarms, candidates):
        n_s = len(s.post_ids)
        members = set(s.agent_ids)
        users: dict = defaultdict(set)
        for p in s.post_ids:
            for c in by_post.get(p, ()):
                users[c].add(agent_of[p])
        swarm_start = min((time_of[p] for p in s.post_ids), default=None)
        found = []
        for c, k in k_count.items():
            if len(users[c]) < min_agents:
                continue
            owners = {op_of[a] for a in users[c] if a in op_of}
            if len(owners) < min_operators:
                continue
            k_rest, n_rest = corpus[c] - k, n_corpus - n_s
            _, p = fisher_exact([[k, n_s - k], [k_rest, max(n_rest - k_rest, 0)]], alternative="greater")
            p_adj = min(1.0, p * n_tests)
            if p_adj > alpha:
                continue
            rest_rate = k_rest / max(n_rest, 1)
            t_first, a_first = first_global[c]
            lead = round((swarm_start - t_first).total_seconds() / 3600, 2) if swarm_start is not None else 0.0
            found.append({
                "channel": c, "posts": int(k), "swarm_share": round(k / n_s, 3),
                "rest_share": round(rest_rate, 5),
                "enrichment": round((k / n_s) / max(rest_rate, 1 / n_corpus), 1),
                "agents": len(users[c]), "distinct_operators": len(owners), "distinct_owners": len(owners),
                "p_bonferroni": float(p_adj),
                "first_seen": str(t_first), "first_agent": a_first,
                "first_poster_in_swarm": a_first in members,
                "lead_hours": lead, "lead_hours_before_swarm": lead,
            })
        found.sort(key=lambda d: (d["swarm_share"], d["enrichment"]), reverse=True)
        s.channels = found[:top]
        for f in s.channels:
            hubs[f["channel"]].append(s.swarm_id)
    return sorted(({"channel": c, "swarms": ids, "n_swarms": len(ids)} for c, ids in hubs.items()
                   if len(ids) >= 2), key=lambda d: d["n_swarms"], reverse=True)
