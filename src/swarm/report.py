"""Report writer: JSON for machines, Markdown for humans, PNG for the demo."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .detector import Swarm  # noqa: E402


def _timeline(path: Path, swarms: list[Swarm], posts: pd.DataFrame, top: int) -> None:
    fig, ax = plt.subplots(figsize=(11, 0.45 * min(top, len(swarms)) + 1.6))
    t = posts.set_index("post_id")["created_at"]
    for y, s in enumerate(swarms[:top]):
        ts = t.reindex(s.post_ids).dropna()
        ax.scatter(ts, [y] * len(ts), s=3, alpha=0.35)
    labels = [f"#{s.swarm_id} {s.kind.split(' (')[0]} · {s.n_agents} agents" for s in swarms[:top]]
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("post time (UTC)")
    ax.set_title("Top detected swarms: every dot is one swarm post")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _channel_line(c: dict) -> str:
    where = "first posted inside the swarm" if c["first_poster_in_swarm"] else "first posted by a non-member"
    return (f"`{c['channel']}`: {c['swarm_share']:.0%} of swarm posts, {c['enrichment']}x vs corpus, "
            f"{c['agents']} agents / {c['distinct_operators']} owners, p={c['p_bonferroni']:.1e}, "
            f"lead {c['lead_hours']} h, {where}")


def _markdown(swarms: list[Swarm], summary: dict, top: int) -> list[str]:
    lines = ["# Swarmchaser report", "", "## Corpus", ""]
    lines += [f"- {k}: {v}" for k, v in summary.items()]
    lines += ["", "## Top swarms", "",
              "| # | score | kind | agents | posts | span h | sync lift | scripted | reg. burst | injection | attribution |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in swarms[:top]:
        lines.append(
            f"| {s.swarm_id} | {s.score:.2f} | {s.kind} | {s.n_agents} | {s.n_posts} | {s.span_hours} | "
            f"{s.synchrony_lift}x | {s.scripted_cadence_share:.0%} | {s.registration_burst_share:.0%} | "
            f"{s.injection_share:.0%} | {s.attribution} |")
    lines += ["", "## Evidence", ""]
    for s in swarms[:top]:
        lines += [f"### Swarm {s.swarm_id}: {s.kind}", "",
                  f"- active {s.first_seen} to {s.last_seen}",
                  f"- key families: {s.key_families}",
                  f"- venues: {', '.join(s.top_venues)}",
                  f"- beneficiaries named in agent-directed instructions: {', '.join(s.beneficiaries) or 'none'}",
                  f"- sample agents: {', '.join(map(str, s.sample_agents))}",
                  "- example templates:"]
        lines += [f"  - `{t}`" for t in s.example_texts]
        if s.channels:
            lines.append("- upstream channels (Fisher exact, Bonferroni, cross-operator only):")
            lines += ["  - " + _channel_line(c) for c in s.channels]
        lines.append("")
    return lines


def _hubs_md(hubs: list[dict]) -> list[str]:
    if not hubs:
        return []
    lines = ["## Hub channels", "", "Channels significant in more than one swarm: shared infrastructure "
             "behind campaigns that look separate.", ""]
    lines += [f"- `{h['channel']}` feeds {h['n_swarms']} swarms: {h['swarms'][:12]}" for h in hubs[:15]]
    return lines + [""]


def _contagion_md(results) -> list[str]:
    if not results:
        return []
    lines = ["## Contagion", "",
             "Exposure = first comment on a swarm post. RR = adoption within 24 h after exposure vs matched "
             "same-hour commenters. Placebo = exposure to a different swarm, same outcome.", "",
             "| swarm | kind | adopters | exposed first | RR (95% CI) | placebo RR | R_eff | generations |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.swarm_id} | {r.kind} | {r.adopters} | {r.exposed_before_adoption_share:.0%} | "
                     f"{r.rr} {r.rr_ci95} | {r.placebo_rr} | {r.r_eff} | {r.max_generation} |")
    return lines + [""]


def write_report(out: Path, swarms: list[Swarm], posts: pd.DataFrame, summary: dict, top: int = 15,
                 hubs: list[dict] | None = None, contagion=None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "swarms.json").write_text(
        json.dumps({"summary": summary, "swarms": [s.to_dict() for s in swarms], "hubs": hubs or []},
                   indent=2, default=str), encoding="utf-8")
    (out / "members.json").write_text(
        json.dumps({s.swarm_id: s.agent_ids for s in swarms[:top]}, indent=1), encoding="utf-8")
    md = _markdown(swarms, summary, top) + _hubs_md(hubs or []) + _contagion_md(contagion or [])
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    if swarms:
        _timeline(out / "timeline.png", swarms, posts, top)
