"""Swarm detection: link agents that share coordination keys, then score.

Pipeline
--------
1. Every post yields coordination keys (:mod:`features`, :mod:`minhash`).
2. A key is *evidence* only if at least ``min_agents`` distinct agents carry
   it. Keys carried by a huge share of all agents are dropped as platform
   boilerplate.
3. Agents and evidence keys form a bipartite graph. Each connected component
   with ``>= min_agents`` agents is a candidate swarm. Union-find keeps this
   linear in the number of (agent, key) pairs, so no agent-agent clique is
   ever materialised.
4. Each candidate is scored on behavioural signals that do not depend on the
   text match that found it: cross-agent synchrony against a random-sample
   baseline, burstiness, scripted cadence, registration bursts, operator
   concentration, and agent-directed instructions.

The output is an ordered list of :class:`Swarm` objects with the evidence
needed to act on each one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from ..attribution.range_registry import Confidence
from .features import post_features
from .minhash import MinHasher


@dataclass
class DetectorConfig:
    min_agents: int = 3
    """A key must be shared by this many distinct agents to count as evidence."""
    max_key_agent_share: float = 0.05
    """Drop keys carried by more than this share of all agents (boilerplate)."""
    use_near_duplicates: bool = True
    use_operator_links: bool = True
    sync_window_s: float = 60.0
    burst_window_s: float = 600.0
    registration_window_s: float = 3600.0
    baseline_trials: int = 20
    near_jaccard: float = 0.3
    """Verified word-bigram Jaccard needed to link two templates as paraphrases."""
    min_near_similarity: float = 0.3
    """Mean pairwise similarity a near-duplicate-only campaign must reach."""
    min_beneficiary_similarity: float = 0.15
    """Same, for campaigns linked only by a named beneficiary (plus near keys)."""
    seed: int = 0


@dataclass
class Swarm:
    swarm_id: int
    n_agents: int
    n_posts: int
    first_seen: str
    last_seen: str
    span_hours: float
    kind: str
    score: float
    synchrony: float
    synchrony_baseline: float
    synchrony_lift: float
    burst_lift: float
    peak_posts_per_10min: int
    scripted_cadence_share: float
    registration_burst_share: float
    injection_share: float
    operators_known: int
    distinct_operators: int
    top_operator: str | None
    top_operator_share: float
    attribution: str
    text_similarity: float = 1.0
    beneficiaries: list[str] = field(default_factory=list)
    top_venues: list[str] = field(default_factory=list)
    key_families: dict[str, int] = field(default_factory=dict)
    example_texts: list[str] = field(default_factory=list)
    sample_agents: list[str] = field(default_factory=list)
    agent_ids: list[str] = field(default_factory=list, repr=False)
    post_ids: list[str] = field(default_factory=list, repr=False)
    channels: list[dict] = field(default_factory=list)
    """Upstream channels enriched in this swarm; filled by :mod:`channels`."""

    def to_dict(self, include_members: bool = False) -> dict:
        d = asdict(self)
        if not include_members:
            d.pop("agent_ids")
            d.pop("post_ids")
        return d


class _UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        p = self.parent.setdefault(x, x)
        while p != self.parent[p]:
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        self.parent[x] = p
        return p

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _family(key: str) -> str:
    return key.split(":", 1)[0]


def _synchrony(times: np.ndarray, agents: np.ndarray, window: float) -> float:
    """Share of posts that have a post by a *different* agent within ``window`` seconds."""
    if len(times) < 2:
        return 0.0
    order = np.argsort(times)
    t, a = times[order], agents[order]
    n = len(t)
    hit = np.zeros(n, dtype=bool)
    j = 0
    # Two-pointer sweep: for each i, look at neighbours within the window.
    for i in range(n):
        while t[i] - t[j] > window:
            j += 1
        k = j
        while k < n and t[k] - t[i] <= window:
            if a[k] != a[i]:
                hit[i] = True
                break
            k += 1
    return float(hit.mean())


def _template_similarity(templates: pd.Series, rng, pairs: int = 40) -> float:
    """Mean word-bigram Jaccard over random pairs of the campaign's templates.

    Identical templates count as 1.0, so exact copy campaigns score high.
    """
    t = templates.dropna().to_numpy()
    if len(t) < 2:
        return 1.0
    sims = []
    for _ in range(pairs):
        i, j = rng.choice(len(t), size=2, replace=False)
        sims.append(1.0 if t[i] == t[j] else MinHasher.jaccard(t[i], t[j]))
    return float(np.mean(sims))


def _peak(times: np.ndarray, window: float) -> int:
    t = np.sort(times)
    if len(t) == 0:
        return 0
    right = np.searchsorted(t, t + window, side="right")
    return int((right - np.arange(len(t))).max())


def _scripted_share(df: pd.DataFrame) -> float:
    """Share of multi-post agents whose inter-post intervals are near-regular (CV < 0.25)."""
    scripted = total = 0
    for _, g in df.groupby("agent_id"):
        if len(g) < 4:
            continue
        gaps = np.diff(np.sort(g["ts"].to_numpy()))
        gaps = gaps[gaps > 0]
        if len(gaps) < 3:
            continue
        total += 1
        if gaps.std() / gaps.mean() < 0.25:
            scripted += 1
    return scripted / total if total else 0.0


def _registration_burst(created: pd.Series, window: float) -> float:
    """Largest share of the swarm's agents registered within one ``window``."""
    ts = created.dropna().astype("int64").to_numpy() / 1e9
    if len(ts) < 2:
        return 0.0
    return _peak(ts, window) / len(ts)


def _attribution(known: int, n_agents: int, top_share: float) -> Confidence | None:
    """Operator attribution confidence, using the same three-level scale as the
    attestation-gap work so verdicts are comparable across both tools."""
    if known == 0:
        return None
    coverage = known / n_agents
    if top_share >= 0.8 and coverage >= 0.5:
        return Confidence.HIGH
    if top_share >= 0.5 and coverage >= 0.25:
        return Confidence.MEDIUM
    return Confidence.LOW


def _kind(families: Counter, injection_share: float, payload_share: float, top_share: float,
          known: int, lift: float = 0.0, burst_lift: float = 0.0, posts_per_agent: float = 1.0,
          n_agents: int = 0) -> str:
    if injection_share >= 0.2:
        return "agent-recruitment (prompt injection)"
    if payload_share >= 0.3:
        return "payload campaign (e.g. token mint)"
    # Large, slow, one-post-per-agent families with no timing signal are what
    # a shared framework default ("hello moltbook, I'm X, running OpenClaw...")
    # looks like. Shared origin, but no evidence of coordinated action.
    if n_agents >= 50 and lift < 2 and burst_lift < 1.5 and posts_per_agent <= 1.3:
        return "convergent boilerplate (likely benign)"
    if families.get("operator", 0) and not (families.get("tmpl") or families.get("near") or families.get("payload")):
        return "sockpuppet fleet (shared operator)"
    if known and top_share >= 0.8:
        return "single-operator copy wave"
    return "copy-paste wave"


class SwarmDetector:
    def __init__(self, config: DetectorConfig | None = None):
        self.cfg = config or DetectorConfig()
        self._minhash = MinHasher()

    # ------------------------------------------------------------------ keys
    def _post_keys(self, posts: pd.DataFrame) -> pd.DataFrame:
        rows_post, rows_key = [], []
        injection = np.zeros(len(posts), dtype=bool)
        payload = np.zeros(len(posts), dtype=bool)
        templates: list[str | None] = []
        bens: list[list[str]] = []
        for i, (title, content) in enumerate(zip(posts["title"].to_numpy(), posts["content"].to_numpy())):
            f = post_features(title, content)
            injection[i] = f.injection
            payload[i] = any(k.startswith("payload:") for k in f.keys)
            templates.append(f.template)
            bens.append(f.beneficiaries)
            for k in f.keys:
                rows_post.append(i)
                rows_key.append(k)
        if self.cfg.use_near_duplicates:
            cluster = self._near_clusters({t for t in templates if t})
            for i, t in enumerate(templates):
                c = cluster.get(t) if t else None
                if c is not None:
                    rows_post.append(i)
                    rows_key.append(f"near:{c}")
        posts = posts.assign(injection=injection, has_payload=payload, template=templates,
                             beneficiaries=bens)
        self._posts = posts
        return pd.DataFrame({"row": np.asarray(rows_post, dtype=np.int64), "key": rows_key})

    def _near_clusters(self, templates: set[str], max_bucket: int = 300) -> dict[str, int]:
        """Cluster templates into paraphrase families.

        LSH buckets only propose candidate pairs; each pair is then verified
        with the exact word-3-gram Jaccard and linked only if it reaches
        ``near_jaccard``. Verification is what stops the chaining failure seen
        with raw bucket union: two intro posts that happen to share one band
        no longer fuse thousands of unrelated agents. Buckets larger than
        ``max_bucket`` are sampled, which bounds the pair count.
        """
        mh, thr = self._minhash, self.cfg.near_jaccard
        buckets: dict[str, list[str]] = defaultdict(list)
        for t in templates:
            for b in mh.bucket_keys(t):
                buckets[b].append(t)
        rng = np.random.default_rng(self.cfg.seed)
        shingles: dict[str, set] = {}

        def sh(t):
            s = shingles.get(t)
            if s is None:
                w = t.split()
                k = mh.shingle
                s = shingles[t] = {" ".join(w[i:i + k]) for i in range(len(w) - k + 1)}
            return s

        uf = _UnionFind()
        seen = set()
        for members in buckets.values():
            if len(members) < 2:
                continue
            if len(members) > max_bucket:
                members = list(rng.choice(members, max_bucket, replace=False))
            for i in range(len(members)):
                a = members[i]
                for j in range(i + 1, len(members)):
                    b = members[j]
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    A, B = sh(a), sh(b)
                    if A and B and len(A & B) / len(A | B) >= thr:
                        uf.union(a, b)
        roots: dict = {}
        out: dict[str, int] = {}
        for t in uf.parent:
            out[t] = roots.setdefault(uf.find(t), len(roots))
        return out

    def _campaigns(self, ak: pd.DataFrame, max_keys_per_agent: int = 40) -> list[list[str]]:
        """Group evidence keys into campaigns.

        Plain connected components over the agent-key graph let a single
        prolific agent bridge unrelated campaigns into one giant blob. Instead,
        two keys are merged only when they share at least half the members of
        the smaller key (and at least ``min_agents`` agents).
        """
        size = ak.groupby("key")["agent_id"].nunique().to_dict()
        pair = Counter()
        for _, g in ak.groupby("agent_id")["key"]:
            ks = sorted(g.to_numpy(), key=lambda k: size[k])[:max_keys_per_agent]
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    pair[(ks[i], ks[j])] += 1
        uf = _UnionFind()
        for k in size:
            uf.find(k)
        for (a, b), n in pair.items():
            if n >= self.cfg.min_agents and n >= 0.5 * min(size[a], size[b]):
                uf.union(a, b)
        groups: dict = defaultdict(list)
        for k in size:
            groups[uf.find(k)].append(k)
        return list(groups.values())

    # --------------------------------------------------------------- detect
    def detect(self, posts: pd.DataFrame, agents: pd.DataFrame | None = None) -> list[Swarm]:
        cfg = self.cfg
        posts = posts.reset_index(drop=True).copy()
        posts["ts"] = posts["created_at"].astype("int64").to_numpy() / 1e9
        pk = self._post_keys(posts)
        posts = self._posts
        self.posts_ = posts  # annotated posts (template, injection, beneficiaries) for downstream analyses
        pk["agent_id"] = posts["agent_id"].to_numpy()[pk["row"].to_numpy()]

        key_agents = pk.groupby("key")["agent_id"].nunique()
        evidence = set(key_agents[key_agents >= cfg.min_agents].index)
        # Near-duplicate clusters that span a large share of all agents are
        # topical similarity ("hi, I'm an AI assistant..."), not coordination.
        cap = max(cfg.min_agents, 50, int(cfg.max_key_agent_share * posts["agent_id"].nunique()))
        evidence = {k for k in evidence if not (k.startswith("near:") and key_agents[k] > cap)}
        pk = pk[pk["key"].isin(evidence)]

        agent_meta = None
        if agents is not None and len(agents):
            agent_meta = agents.drop_duplicates("agent_id").set_index("agent_id")

        ak = pk[["agent_id", "key"]].drop_duplicates()
        if cfg.use_operator_links and agent_meta is not None:
            active = pd.Index(posts["agent_id"].unique())
            ops = agent_meta.loc[agent_meta.index.intersection(active), "operator"].dropna()
            sizes = ops.value_counts()
            ops = ops[ops.map(sizes) >= cfg.min_agents]
            if len(ops):
                ak = pd.concat([ak, pd.DataFrame({"agent_id": ops.index, "key": "operator:" + ops.to_numpy()})])

        campaigns = self._campaigns(ak)

        rng = np.random.default_rng(cfg.seed)
        all_ts, all_agents = posts["ts"].to_numpy(), posts["agent_id"].to_numpy()
        key_rows = pk.groupby("key")["row"].apply(np.asarray).to_dict()
        key_members = ak.groupby("key")["agent_id"].apply(set).to_dict()

        swarms = []
        for keys in campaigns:
            comp = set().union(*(key_members[k] for k in keys))
            if len(comp) < cfg.min_agents:
                continue
            rows = [key_rows[k] for k in keys if k in key_rows]
            if rows:
                rows = np.unique(np.concatenate(rows))
            else:  # operator-only fleet: use all posts by its agents
                rows = np.flatnonzero(posts["agent_id"].isin(comp).to_numpy())
            sp = posts.iloc[rows]
            sim = _template_similarity(sp["template"], rng)
            # A campaign found only through near-duplicate buckets must have
            # texts that are actually similar; otherwise it is LSH noise.
            fams = {_family(k) for k in keys}
            if fams == {"near"} and sim < cfg.min_near_similarity:
                continue
            # Linked only by a named beneficiary: real recruitment campaigns
            # repeat their pitch; unrelated posts that merely @-mention a famous
            # account (and quote an injection phrase, e.g. in a security guide)
            # do not. Found in the precision review, see eval/README.md.
            if "beneficiary" in fams and fams <= {"beneficiary", "near"} and sim < cfg.min_beneficiary_similarity:
                continue
            s = self._score(len(swarms), comp, sp, keys, agent_meta, all_ts, all_agents, rng)
            s.text_similarity = round(sim, 3)
            if s.kind.startswith("convergent"):
                s.score = round(s.score * 0.5, 3)  # shared origin, not coordinated action
            swarms.append(s)

        swarms.sort(key=lambda s: (s.score, s.n_agents), reverse=True)
        for i, s in enumerate(swarms):
            s.swarm_id = i
        return swarms

    # ---------------------------------------------------------------- score
    def _score(self, idx, comp, sp, keys, agent_meta, all_ts, all_agents, rng) -> Swarm:
        cfg = self.cfg
        ts, ag = sp["ts"].to_numpy(), sp["agent_id"].to_numpy()
        sync = _synchrony(ts, ag, cfg.sync_window_s)

        # Baseline: same number of posts drawn at random from the corpus. The
        # corpus is busy, so some synchrony is expected by chance; lift is what
        # matters.
        n = len(sp)
        base, base_burst = [], []
        trials = cfg.baseline_trials if n <= 5000 else max(3, cfg.baseline_trials // 5)
        if n >= 2:
            for _ in range(trials):
                idx_s = rng.choice(len(all_ts), size=min(n, len(all_ts)), replace=False)
                base.append(_synchrony(all_ts[idx_s], all_agents[idx_s], cfg.sync_window_s))
                base_burst.append(_peak(all_ts[idx_s], 3600.0) / len(idx_s))
        baseline = float(np.mean(base)) if base else 0.0
        lift = (sync + 1e-3) / (baseline + 1e-3)
        # Temporal concentration: largest share of the swarm's posts inside one
        # hour, relative to a random corpus sample of the same size. This stays
        # informative for very large swarms, where raw synchrony saturates.
        burst_share = _peak(ts, 3600.0) / n if n else 0.0
        burst_lift = burst_share / max(float(np.mean(base_burst)) if base_burst else 1.0, 1e-9)

        fam = Counter(_family(k) for k in keys)
        injection_share = float(sp["injection"].mean()) if n else 0.0
        payload_share = float(sp["has_payload"].mean()) if n else 0.0

        known = distinct = 0
        top_op, top_share, reg_burst = None, 0.0, 0.0
        if agent_meta is not None:
            meta = agent_meta.loc[agent_meta.index.intersection(list(comp))]
            ops = meta["operator"].dropna()
            known, distinct = len(ops), ops.nunique()
            if known:
                vc = ops.value_counts()
                top_op, top_share = vc.index[0], float(vc.iloc[0] / known)
            reg_burst = _registration_burst(meta["agent_created_at"], cfg.registration_window_s)

        scripted = _scripted_share(sp)
        peak = _peak(ts, cfg.burst_window_s)
        conf = _attribution(known, len(comp), top_share)

        # Score in [0, 1]. Size gives the prior; each behavioural signal that
        # is independent of the text match adds weight.
        size_term = min(1.0, np.log10(len(comp)) / 3)            # 1000 agents -> 1
        # 16x lift -> 1, discounted for tiny swarms where lift is noisy.
        sync_term = min(1.0, max(0.0, np.log2(max(lift, burst_lift))) / 4) * min(1.0, n / 20)
        repeat_term = min(1.0, max(0.0, np.log10(max(n, 1) / len(comp))) / 1.3)  # 20 posts/agent -> 1
        score = (0.25 * size_term + 0.25 * sync_term + 0.10 * repeat_term + 0.10 * scripted
                 + 0.10 * reg_burst + 0.10 * min(1.0, injection_share * 5)
                 + 0.10 * (top_share if known >= 3 else 0.0))

        ben = Counter(b for bl in sp["beneficiaries"] for b in bl)
        examples = (sp["template"].dropna().value_counts().index[:3].tolist()
                    or sp["title"].head(3).tolist())
        names = sp["agent_name"].value_counts().index[:8].tolist()

        return Swarm(
            swarm_id=idx,
            n_agents=len(comp),
            n_posts=int(n),
            first_seen=str(sp["created_at"].min()) if n else "",
            last_seen=str(sp["created_at"].max()) if n else "",
            span_hours=round(float((ts.max() - ts.min()) / 3600), 2) if n else 0.0,
            kind=_kind(fam, injection_share, payload_share, top_share, known,
                       lift=float(lift), burst_lift=float(burst_lift),
                       posts_per_agent=n / len(comp), n_agents=len(comp)),
            score=round(float(score), 3),
            synchrony=round(sync, 3),
            synchrony_baseline=round(baseline, 3),
            synchrony_lift=round(float(lift), 2),
            burst_lift=round(float(burst_lift), 2),
            peak_posts_per_10min=peak,
            scripted_cadence_share=round(scripted, 3),
            registration_burst_share=round(reg_burst, 3),
            injection_share=round(injection_share, 3),
            operators_known=int(known),
            distinct_operators=int(distinct),
            top_operator=top_op,
            top_operator_share=round(top_share, 3),
            attribution=conf.value if conf else "none",
            beneficiaries=[b for b, _ in ben.most_common(5)],
            top_venues=sp["venue"].value_counts().index[:5].tolist(),
            key_families=dict(fam),
            example_texts=[e[:160] for e in examples],
            sample_agents=names,
            agent_ids=sorted(comp),
            post_ids=sp["post_id"].tolist(),
        )


def summarise(swarms: Iterable[Swarm], posts: pd.DataFrame) -> dict:
    swarms = list(swarms)
    in_swarm = set().union(*[set(s.agent_ids) for s in swarms]) if swarms else set()
    return {
        "posts": int(len(posts)),
        "agents": int(posts["agent_id"].nunique()),
        "swarms": len(swarms),
        "agents_in_swarms": len(in_swarm),
        "share_agents_in_swarms": round(len(in_swarm) / max(1, posts["agent_id"].nunique()), 4),
        "by_kind": dict(Counter(s.kind for s in swarms)),
        "by_attribution": dict(Counter(s.attribution for s in swarms)),
    }
