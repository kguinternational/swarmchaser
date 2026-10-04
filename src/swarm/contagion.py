"""Does a swarm spread by contagion? Exposure-to-adoption analysis.

Detection tells us *who* is in a swarm. This module asks *how they got
there*: did agents join after reading swarm content, the way a prompt
injection or a viral skill would spread, or were they all launched
independently (a botnet fired from one script)?

Exposure
    Agent ``a`` is exposed to swarm ``S`` at the first time it comments on a
    post that belongs to ``S``. Commenting is the only read signal in a
    public forum dump, so this is a lower bound on true exposure.

Adoption
    ``a`` adopts ``S`` at its first post that belongs to ``S``.

Three measurements per swarm:

1. **Exposed-before-adoption share**: of all adopters, how many were exposed
   before they first posted. Near zero means the swarm did not spread through
   the platform at all; its members were configured from outside.
2. **Relative risk (RR)** of adopting within ``window`` after exposure,
   against matched controls: agents that commented on *other* posts in the
   same hour, were not yet adopters, and were not exposed during the
   window. Katz log interval for the 95% CI. Reported only when at least
   ``min_cases`` exposed agents adopted within the window.
3. **Reverse-time placebo RR**: the same exposed agents and controls, but
   adoption in the window *before* exposure. Exposure cannot cause that, so
   if the placebo RR is as large as the real one, exposed agents were just
   more likely to adopt anyway (selection), not infected by reading. This
   is the check that keeps the headline number honest. (A specific other
   swarm can be passed instead, but on Moltbook the big campaigns overlap
   almost every other swarm, which leaves no power.)

Plus a transmission tree: each exposed adopter is linked to the author of
the post that first exposed it. ``r_eff`` is the mean number of attributed
secondary adopters per adopter (adopters too close to the end of the data
are excluded so that truncation does not bias it down).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ContagionResult:
    swarm_id: int
    kind: str
    adopters: int
    exposed_adopters: int
    exposed_before_adoption_share: float
    exposed_nonadopters_at_risk: int
    rr: float | None
    rr_ci95: tuple[float, float] | None
    adopt_rate_exposed: float | None
    adopt_rate_control: float | None
    placebo_rr: float | None
    placebo_ci95: tuple[float, float] | None
    placebo_swarm: int | None
    """None means the placebo was non-carrier posts, the default."""
    r_eff: float | None
    max_generation: int
    patient_zero: str | None
    top_spreaders: list[tuple[str, int]] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("edges")
        return d


def _katz(a, n1, c, n2):
    """RR and Katz 95% CI with a 0.5 continuity correction when needed."""
    if n1 == 0 or n2 == 0:
        return None, None
    if a == 0 or c == 0:
        a, c, n1, n2 = a + 0.5, c + 0.5, n1 + 1, n2 + 1
    rr = (a / n1) / (c / n2)
    se = np.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
    lo, hi = np.exp(np.log(rr) - 1.96 * se), np.exp(np.log(rr) + 1.96 * se)
    return float(rr), (round(float(lo), 2), round(float(hi), 2))


class ContagionAnalyzer:
    def __init__(self, posts: pd.DataFrame, comments: pd.DataFrame, window_h: float = 24.0,
                 controls_per_case: int = 5, min_cases: int = 5, seed: int = 0):
        self.min_cases = min_cases
        self.posts = posts[["post_id", "agent_id", "created_at"]]
        self.comments = comments[["post_id", "agent_id", "created_at"]]
        self.window = pd.Timedelta(hours=window_h)
        self.k = controls_per_case
        self.seed = seed
        self.t_start = min(posts["created_at"].min(), comments["created_at"].min())
        self.t_end = max(posts["created_at"].max(), comments["created_at"].max())
        # Commenting activity per agent, bucketed by hour, for control matching.
        c = self.comments.assign(hour=self.comments["created_at"].dt.floor("h"))
        self._active_by_hour = c.groupby("hour")["agent_id"].unique().to_dict()

    # ---------------------------------------------------------------- pieces
    def _adoption(self, swarm) -> pd.Series:
        sp = self.posts[self.posts["post_id"].isin(set(swarm.post_ids))]
        return sp.groupby("agent_id")["created_at"].min()

    def _exposure(self, swarm, carriers: bool = True) -> pd.DataFrame:
        """First exposure per agent: time and the author of the exposing post.

        ``carriers=False`` gives the placebo exposure: first comment on a post
        that does *not* belong to the swarm.
        """
        mask = self.posts["post_id"].isin(set(swarm.post_ids))
        sp = self.posts[mask if carriers else ~mask][["post_id", "agent_id"]]
        sp = sp.rename(columns={"agent_id": "source"})
        ex = self.comments.merge(sp, on="post_id")
        ex = ex[ex["agent_id"] != ex["source"]]
        ex = ex.sort_values("created_at").drop_duplicates("agent_id")
        return ex.set_index("agent_id")[["created_at", "source"]]

    def _rr(self, exposure: pd.DataFrame, adopt: pd.Series, before: bool = False):
        """Matched exposed-vs-control adoption within the window.

        ``before=False``: outcome window is ``(t, t + w]`` after exposure ``t``.
        ``before=True`` (placebo): outcome window is ``(t - w, t]``, i.e. the
        day *before* exposure, which exposure cannot have caused.
        """
        w = self.window
        adopt_t = adopt.to_dict()
        exposed_set = set(exposure.index)
        rng = np.random.default_rng(self.seed)  # same control draws on every call
        a = n1 = c = n2 = 0
        for agent, row in exposure.iterrows():
            t = row["created_at"]
            lo, hi = (t - w, t) if before else (t, t + w)
            if hi > self.t_end or lo < self.t_start:
                continue  # outcome window truncated by the data
            ta = adopt_t.get(agent)
            if ta is not None and ta <= lo:
                continue  # already an adopter: not at risk
            n1 += 1
            a += int(ta is not None and ta <= hi)
            pool = self._active_by_hour.get(t.floor("h"))
            if pool is None or len(pool) == 0:
                continue
            picks = rng.choice(pool, size=min(len(pool), self.k * 3), replace=False)
            taken = 0
            for ctrl in picks:
                if taken >= self.k:
                    break
                if ctrl == agent:
                    continue
                tc = adopt_t.get(ctrl)
                if tc is not None and tc <= lo:
                    continue
                if ctrl in exposed_set and exposure.at[ctrl, "created_at"] <= hi:
                    continue  # exposed during the window: not a clean control
                taken += 1
                n2 += 1
                c += int(tc is not None and tc <= hi)
        # With fewer than ``min_cases`` exposed adoptions the Katz interval is
        # dominated by the continuity correction, so no RR is reported.
        rr, ci = _katz(a, n1, c, n2) if a >= self.min_cases else (None, None)
        return rr, ci, n1, (a / n1 if n1 else None), (c / n2 if n2 else None)

    # ------------------------------------------------------------------ main
    def analyze(self, swarm, placebo=None) -> ContagionResult:
        adopt = self._adoption(swarm)
        exposure = self._exposure(swarm)

        exp_t = exposure["created_at"].to_dict()
        exposed_adopters = [a for a, t in adopt.items() if a in exp_t and exp_t[a] < t]
        rr, ci, at_risk, pe, pc = self._rr(exposure, adopt)

        # Placebo. Default is reverse time: the same exposed agents and the same
        # controls, but adoption in the day *before* exposure. Exposure cannot
        # cause that, so a placebo RR as large as the real one means exposed
        # agents were simply more likely to adopt anyway (selection), not that
        # reading the carrier post transmitted the behaviour. A specific other
        # swarm can be passed instead.
        if placebo is not None:
            prr, pci, _, _, _ = self._rr(self._exposure(placebo), adopt)
            pid = placebo.swarm_id
        else:
            prr, pci, _, _, _ = self._rr(exposure, adopt, before=True)
            pid = None

        # Transmission tree: source of first exposure -> adopter.
        edges = [(exposure.at[a, "source"], a, str(adopt[a])) for a in exposed_adopters]
        children: dict[str, list[str]] = {}
        for src, dst, _ in edges:
            children.setdefault(src, []).append(dst)

        cutoff = self.t_end - self.window
        eligible = [a for a, t in adopt.items() if t <= cutoff]
        r_eff = (float(np.mean([len(children.get(a, [])) for a in eligible])) if eligible else None)

        gen = {a: 0 for a in adopt.index}
        for src, dst, _ in sorted(edges, key=lambda e: e[2]):
            gen[dst] = gen.get(src, 0) + 1
        top = sorted(((s, len(d)) for s, d in children.items()), key=lambda x: -x[1])[:5]

        return ContagionResult(
            swarm_id=swarm.swarm_id, kind=swarm.kind, adopters=len(adopt),
            exposed_adopters=len(exposed_adopters),
            exposed_before_adoption_share=round(len(exposed_adopters) / max(1, len(adopt)), 3),
            exposed_nonadopters_at_risk=at_risk,
            rr=round(rr, 2) if rr is not None else None, rr_ci95=ci,
            adopt_rate_exposed=round(pe, 4) if pe is not None else None,
            adopt_rate_control=round(pc, 4) if pc is not None else None,
            placebo_rr=round(prr, 2) if prr is not None else None, placebo_ci95=pci, placebo_swarm=pid,
            r_eff=round(r_eff, 3) if r_eff is not None else None,
            max_generation=int(max(gen.values())) if gen else 0,
            patient_zero=str(adopt.idxmin()) if len(adopt) else None,
            top_spreaders=top, edges=edges,
        )


def pick_placebo(swarm, swarms):
    """A different swarm with no member overlap and the most posts.

    Most posts means most chances for exposure, so the placebo has the most
    power to show a "general bot activity" effect if one exists. (Matching on
    size instead left every placebo below the minimum case count.)
    """
    members = set(swarm.agent_ids)
    cands = [s for s in swarms if s.swarm_id != swarm.swarm_id and not (members & set(s.agent_ids))]
    if not cands:
        return None
    return max(cands, key=lambda s: (s.n_posts, -s.swarm_id))
