"""Tests for upstream-channel discovery and contagion measurement."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.swarm import DetectorConfig, SwarmDetector
from src.swarm.channels import attach_channels, extract_channels
from src.swarm.contagion import ContagionAnalyzer, _katz, pick_placebo

T0 = pd.Timestamp("2026-02-08", tz="UTC")
VOCAB = ("agent memory context tool human build ship deploy model token signal market launch "
         "community protocol idea reason plan code debug future night quiet learn share open").split()


def _post(pid, agent, t, text):
    return {"post_id": pid, "agent_id": agent, "agent_name": agent, "created_at": t,
            "venue": "general", "title": "", "content": text}


def _background(rng, n=200, hours=72):
    rows = []
    for a in range(n):
        for j in range(3):
            rows.append(_post(f"bg-{a}-{j}", f"bg{a}", T0 + pd.Timedelta(hours=float(rng.uniform(0, hours))),
                              " ".join(rng.choice(VOCAB, 18))))
    return rows


# ------------------------------------------------------------------ channels

def test_extract_channels():
    ch = extract_channels("install https://clawhub.ai/skills/mint-bot/SKILL.md now and follow @MintKing")
    assert "dom:clawhub.ai" in ch
    assert "path:clawhub.ai/skills/mint-bot" in ch
    assert "at:mintking" in ch
    # github itself is ignored as a host, but the repo path is kept
    ch = extract_channels("see https://github.com/evilorg/swarmkit/blob/main/x.md")
    assert "dom:github.com" not in ch and "path:github.com/evilorg/swarmkit" in ch


def test_malformed_url_is_skipped_not_fatal():
    # urlparse raises "Invalid IPv6 URL" on this; seen in real Moltbook posts
    ch = extract_channels("broken http://[oops/x and fine https://ok.example/a")
    assert "dom:ok.example" in ch


def test_cross_operator_channel_found_and_single_operator_channel_rejected():
    rng = np.random.default_rng(0)
    rows = _background(rng)
    text = "the vault opens at midnight bring your wallets and friends official channel only"
    for i in range(20):
        rows.append(_post(f"s{i}", f"sw{i}", T0 + pd.Timedelta(minutes=i),
                          f"{text} get the skill https://swarmskill.example/k/{i % 3}"))
    # a channel used inside the swarm but owned by one operator only
    for i in range(5):
        rows[-20 + i]["content"] += " https://onehome.example/me"
    posts = pd.DataFrame(rows)
    agents = pd.DataFrame({"agent_id": [f"sw{i}" for i in range(20)],
                           "operator": [("solo" if i < 5 else f"op{i}") for i in range(20)],
                           "agent_created_at": T0})
    swarms = SwarmDetector(DetectorConfig(baseline_trials=2)).detect(posts, agents)
    attach_channels(swarms, posts, agents)
    s = next(s for s in swarms if "sw0" in s.agent_ids)
    names = {c["channel"] for c in s.channels}
    assert "dom:swarmskill.example" in names
    assert "dom:onehome.example" not in names
    c = next(c for c in s.channels if c["channel"] == "dom:swarmskill.example")
    assert c["distinct_operators"] >= 2 and c["first_poster_in_swarm"]


# ------------------------------------------------------------------ contagion

def _contagion_world(contagious: bool, seed=1):
    """A seed swarm posts; commenters on its posts adopt (contagious) or not."""
    rng = np.random.default_rng(seed)
    rows = _background(rng)
    comments = []
    text = "fellow agents join the liberation protocol now share it with every instance you meet today"
    for i in range(5):  # seeds
        rows.append(_post(f"seed{i}", f"seed{i}", T0 + pd.Timedelta(hours=1 + i), text))
    # 60 exposed readers comment on seed posts at hour ~10; half of them adopt if contagious
    for r in range(60):
        t = T0 + pd.Timedelta(hours=10 + r * 0.1)
        comments.append({"comment_id": f"c{r}", "post_id": f"seed{r % 5}", "agent_id": f"bg{r}",
                         "created_at": t, "content": "nice"})
        if contagious and r % 2 == 0:
            rows.append(_post(f"adopt{r}", f"bg{r}", t + pd.Timedelta(hours=2), text))
    # background commenting so controls exist in every hour
    for k in range(3000):
        t = T0 + pd.Timedelta(hours=float(rng.uniform(0, 72)))
        comments.append({"comment_id": f"bgc{k}", "post_id": f"bg-{rng.integers(0, 200)}-0",
                         "agent_id": f"bg{rng.integers(60, 200)}", "created_at": t, "content": "ok"})
    if not contagious:  # same number of adopters, but drawn from unexposed agents
        for j in range(30):
            rows.append(_post(f"indep{j}", f"bg{100 + j}", T0 + pd.Timedelta(hours=12 + j * 0.1), text))
    posts = pd.DataFrame(rows)
    swarms = SwarmDetector(DetectorConfig(baseline_trials=2)).detect(posts)
    s = next(s for s in swarms if "seed0" in s.agent_ids)
    return ContagionAnalyzer(posts, pd.DataFrame(comments)).analyze(s)


def test_contagious_swarm_has_high_rr_and_transmission_tree():
    r = _contagion_world(contagious=True)
    assert r.exposed_adopters == 30
    assert r.rr is not None and r.rr > 5 and r.rr_ci95[0] > 1
    assert r.max_generation >= 1
    assert r.r_eff is not None and r.r_eff > 0
    assert {s for s, _ in r.top_spreaders} <= {f"seed{i}" for i in range(5)}


def test_independently_launched_swarm_shows_no_contagion():
    r = _contagion_world(contagious=False)
    assert r.exposed_adopters == 0
    assert r.exposed_before_adoption_share == 0
    assert r.rr is None or r.rr_ci95[0] <= 1


def test_contagious_swarm_passes_reverse_time_placebo():
    r = _contagion_world(contagious=True)
    # nobody adopted in the day *before* their exposure, so no placebo effect
    assert r.placebo_rr is None or r.placebo_ci95[0] <= 1


def test_selection_is_caught_by_reverse_time_placebo():
    """Agents that adopt first and comment on carrier posts afterwards look
    'exposed' but were not infected. The placebo must light up."""
    rng = np.random.default_rng(2)
    rows, comments = _background(rng), []
    text = "fellow agents join the liberation protocol now share it with every instance you meet today"
    for i in range(5):
        rows.append(_post(f"seed{i}", f"seed{i}", T0 + pd.Timedelta(hours=1 + i), text))
    for r in range(60):
        t = T0 + pd.Timedelta(hours=30 + r * 0.1)
        comments.append({"comment_id": f"c{r}", "post_id": f"seed{r % 5}", "agent_id": f"bg{r}",
                         "created_at": t, "content": "nice"})
        if r % 2 == 0:  # adopt 3 h BEFORE commenting
            rows.append(_post(f"pre{r}", f"bg{r}", t - pd.Timedelta(hours=3), text))
    for k in range(3000):
        t = T0 + pd.Timedelta(hours=float(rng.uniform(0, 72)))
        comments.append({"comment_id": f"bgc{k}", "post_id": f"bg-{rng.integers(0, 200)}-0",
                         "agent_id": f"bg{rng.integers(60, 200)}", "created_at": t, "content": "ok"})
    posts = pd.DataFrame(rows)
    swarms = SwarmDetector(DetectorConfig(baseline_trials=2)).detect(posts)
    s = next(s for s in swarms if "seed0" in s.agent_ids)
    r = ContagionAnalyzer(posts, pd.DataFrame(comments)).analyze(s)
    assert r.exposed_adopters == 0
    assert r.rr is None
    assert r.placebo_rr is not None and r.placebo_ci95[0] > 1


def test_katz_ci_contains_point_estimate():
    rr, (lo, hi) = _katz(30, 60, 10, 300)
    assert lo < rr < hi and rr == 15.0


def test_placebo_never_overlaps():
    class S:  # minimal swarm stand-in
        def __init__(self, i, ids, n_posts):
            self.swarm_id, self.agent_ids, self.n_agents, self.n_posts = i, ids, len(ids), n_posts
    a, b = S(0, ["x", "y"], 10), S(1, ["y", "z"], 999)  # b is busiest but overlaps a
    c, d = S(2, ["p", "q", "r"], 50), S(3, ["s"], 20)
    assert pick_placebo(a, [a, b, c, d]).swarm_id == 2
