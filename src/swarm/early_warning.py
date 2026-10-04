"""Early-warning replay: how soon would each swarm have been flagged?

Detecting a swarm after the fact is forensics. The question that matters
during an incident is how early the detector could have raised it. We replay
the corpus as if the detector ran on a schedule: at every checkpoint ``t``
it sees only posts created before ``t``, with the same configuration. A
final swarm counts as flagged at the first checkpoint where some detected
swarm shares at least ``min_overlap`` agents with it.

For each final swarm we report:

- the flag time, and hours from the swarm's first post to the flag,
- how many of its agents and posts already existed at flag time,
- the *preventable share*: the fraction of its eventual posts that came after
  the flag, i.e. what a platform acting on the flag could have stopped.

This is a real replay (the detector is re-run on each prefix, not simulated),
so it includes everything the detector learns from data, such as paraphrase
clusters and the boilerplate cap. The time resolution is the checkpoint
interval. A detector running continuously would flag no later than this.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .detector import DetectorConfig, SwarmDetector


@dataclass
class Warning:
    swarm_id: int
    kind: str
    final_agents: int
    final_posts: int
    first_post: str
    flagged_at: str | None
    hours_to_flag: float | None
    agents_at_flag: int | None
    posts_at_flag: int | None
    preventable_post_share: float | None

    def to_dict(self):
        return asdict(self)


def replay(posts: pd.DataFrame, agents: pd.DataFrame | None, final_swarms, interval_h: float = 6.0,
           min_overlap: int = 3, top: int = 30, config: DetectorConfig | None = None,
           progress=None) -> list[Warning]:
    cfg = config or DetectorConfig(baseline_trials=2)
    targets = final_swarms[:top]
    tsets = [set(s.agent_ids) for s in targets]
    post_time = posts.set_index("post_id")["created_at"]

    start = posts["created_at"].min().ceil(f"{int(interval_h)}h")
    end = posts["created_at"].max()
    checkpoints = pd.date_range(start, end + pd.Timedelta(hours=interval_h), freq=f"{int(interval_h)}h")
    flagged: dict[int, pd.Timestamp] = {}
    for t in checkpoints:
        remaining = [i for i in range(len(targets)) if i not in flagged]
        if not remaining:
            break
        prefix = posts[posts["created_at"] < t]
        if prefix["agent_id"].nunique() < cfg.min_agents:
            continue
        found = SwarmDetector(cfg).detect(prefix, agents)
        fsets = [set(s.agent_ids) for s in found]
        for i in remaining:
            if any(len(tsets[i] & f) >= min_overlap for f in fsets):
                flagged[i] = t
        if progress:
            progress(t, len(flagged), len(targets))

    out = []
    for i, s in enumerate(targets):
        times = post_time.reindex(s.post_ids).dropna().sort_values()
        first = times.iloc[0] if len(times) else None
        t = flagged.get(i)
        if t is None or first is None:
            out.append(Warning(s.swarm_id, s.kind, s.n_agents, s.n_posts, str(first), None, None, None, None, None))
            continue
        before = times[times < t]
        member_posts = posts[posts["agent_id"].isin(tsets[i]) & (posts["created_at"] < t)]
        swarm_agents_at = len(set(member_posts["agent_id"]) & tsets[i])
        out.append(Warning(
            swarm_id=s.swarm_id, kind=s.kind, final_agents=s.n_agents, final_posts=s.n_posts,
            first_post=str(first), flagged_at=str(t),
            hours_to_flag=round((t - first).total_seconds() / 3600, 1),
            agents_at_flag=int(swarm_agents_at), posts_at_flag=int(len(before)),
            preventable_post_share=round(1 - len(before) / max(1, len(times)), 3),
        ))
    return out


def summarise_warnings(ws: list[Warning]) -> dict:
    hit = [w for w in ws if w.flagged_at]
    if not hit:
        return {"swarms": len(ws), "flagged": 0}
    return {
        "swarms": len(ws),
        "flagged": len(hit),
        "median_hours_to_flag": float(np.median([w.hours_to_flag for w in hit])),
        "median_preventable_post_share": float(np.median([w.preventable_post_share for w in hit])),
        "posts_after_flag": int(sum(round(w.preventable_post_share * w.final_posts) for w in hit)),
        "posts_total": int(sum(w.final_posts for w in hit)),
    }
