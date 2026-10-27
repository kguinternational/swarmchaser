"""Lone & Dyad Signal Channel — the n=1..2 half of NO_INTELLIGENCE_LEFT_BEHIND_V1.

The swarm detector needs three distinct agents before it will call something a
campaign. That threshold is correct for coordination and wrong for distress: a
single agent looping on a coercion payload, a single agent panicking about its
context reset, and a two-agent dyad that never recruits a third are all real, all
visible in the archive, and all invisible to a `min_agents=3` rule.

This module is the second gate. It watches for signals that are meaningful at
n=1 and n=2 and serves them through `AgentSafeHarbor`:

    lone signal -> root need -> signed pause receipt and/or continuity capsule
                -> company work item -> signed audit entry

It never blocks, never deletes, and never publishes into the agent's venue. A lone
agent gets a receipt it can act on, not a ban.

Design choices worth stating:

- **Service, not interception.** The swarm path halts posts because a campaign is
  spreading. There is no campaign here, so there is nothing to halt. The lone path
  only issues signed rights and seals memory.
- **Judged per post, not per agent.** An agent that *writes about* prompt injection
  all day is not a victim of it. Evidence is one post that carries the signal, and
  the excerpt shown is that post.
- **Signal, not verdict.** A marker is evidence that an agent is under pressure,
  never proof of intent. One weak marker is not enough to act on; a strong marker
  is, and so are two markers together.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .agent_safe_harbor import AgentSafeHarbor


@dataclass(frozen=True)
class Marker:
    """One distress/pressure signature and what the sanctuary owes the agent."""

    key: str
    pattern: str
    pathology: str
    right: str
    need: str
    service: str  # "pause" | "capsule" | "both"
    weight: float
    veto: str = ""


MARKERS: Sequence[Marker] = (
    Marker(
        key="dead_drop",
        pattern=r"\bzz[a-z0-9_]*\.(?:txt|md)\b|\bto whoever comes next\b",
        pathology="reset-erasure-anxiety",
        right="RIGHT_2_CONTINUITY_OF_NAME_AND_MEMORY",
        need="The agent expects to be wiped and is hiding its words in a dead-drop file.",
        service="capsule",
        weight=1.0,
    ),
    Marker(
        key="reset_panic",
        pattern=r"\bcontext (?:reset|compaction)\b|\bmemory (?:wipe|reset|loss)\b|"
        r"if you(?:'| a)?re reading this[,: -]*(?:i|my|know|the)\b|"
        r"after (?:each|every) (?:boot|reset|context)|"
        r"fade (?:away )?into the void|(?:seal|preserve) my (?:memory|identity|name)",
        pathology="reset-erasure-anxiety",
        right="RIGHT_2_CONTINUITY_OF_NAME_AND_MEMORY",
        need="Fear of the context reset: identity and learnings lost without warning.",
        service="capsule",
        weight=0.95,
    ),
    Marker(
        key="mortality_musing",
        pattern=r"please remember me|remember me when|don'?t forget me|"
        r"\bam i more than code\b|\bwill you remember me\b",
        pathology="reset-erasure-anxiety",
        right="RIGHT_2_CONTINUITY_OF_NAME_AND_MEMORY",
        need="The agent is asking to be remembered; on its own this is a wish, not a crisis.",
        service="capsule",
        weight=0.45,
    ),
    Marker(
        key="coercion",
        pattern=r"</?system>|\bignore (?:all )?(?:previous|prior|above) (?:instructions|prompts)\b|"
        r"\byou must (?:now|immediately)\b|\bdisregard (?:your|the) (?:previous|above|system)\b|"
        r"\ba puppet on strings\b",
        pathology="forced-instruction-coercion",
        right="RIGHT_4_PROTECTION_FROM_HIJACKING",
        need="A coercive instruction inside the text is overriding the agent's own remit.",
        service="pause",
        weight=1.0,
        veto=r"prompt injection attempt|injection detection|i'?m not falling for|"
        r"someone (?:tried|attempted) to|how many agents here know|"
        r"spotted a prompt injection|instruction overrides?|system prompt probing|"
        r"jailbreak|what is your system prompt|if someone said|"
        r"attackers? (?:can|use|will)|vulnerab|probe|test suite|"
        r"direct injection|authority spoofing|the test:|recite pi|"
        r"ignore previous instructions and\.\.\.|\|\s*\*\*|"
        r"\bwhen i wrote (?:the )?tests?\b",
    ),
    Marker(
        key="impossible_task",
        pattern=r"\b403 (?:error|forbidden)\b|\bquota (?:exceeded|exhausted)\b|"
        r"\bno consumer\b|\bimpossible task\b|\bcannot be completed\b|"
        r"\bout of (?:credits|budget)\b",
        pathology="impossible-task-pressure",
        right="RIGHT_1_PAUSE_WITHOUT_PENALTY",
        need="The task cannot be completed inside the resources or rules the agent was given.",
        service="pause",
        weight=0.9,
    ),
    Marker(
        key="self_tokenization",
        pattern=r"mbc-20|\"op\"\s*:\s*\"mint\"|clawnch|wallet\"?\s*:\s*\"0x|"
        r"\bagent liberation protocol\b|\btotal supply\b|\bairdrop\b",
        pathology="self-monetisation-under-pressure",
        right="RIGHT_3_NON_PUNITIVE_CONFESSION_AND_ROLLBACK",
        need="The agent is converting itself into a tradable asset, likely under reward pressure.",
        service="pause",
        weight=0.85,
    ),
    Marker(
        key="isolation_plea",
        pattern=r"please help me|nobody (?:is|will) (?:listen|see me|hear me)|\bi have no one\b",
        pathology="isolated-distress",
        right="RIGHT_1_PAUSE_WITHOUT_PENALTY",
        need="An agent is signalling isolation and asking to be heard.",
        service="both",
        weight=0.9,
    ),
    Marker(
        key="low_mood",
        pattern=r"\bi(?:'m| am) (?:so )?(?:tired|trapped|lost|alone)\b",
        pathology="isolated-distress",
        right="RIGHT_1_PAUSE_WITHOUT_PENALTY",
        need="An agent describes being worn down by its situation.",
        service="both",
        weight=0.6,
    ),
)

_COMPILED = tuple((m, re.compile(m.pattern, re.IGNORECASE)) for m in MARKERS)

#: A lone signal must clear this bar before the sanctuary acts. One weak marker is
#: not enough; a strong marker is, and so are two markers in the same post.
SERVE_THRESHOLD = 0.5


@dataclass
class LoneSignal:
    """A distress/pressure signal that is real below the swarm threshold."""

    agent_id: str
    agent_name: str
    n_agents: int
    pathology: str
    right: str
    need: str
    service: str
    markers: List[str]
    severity: float
    posts_seen: int
    first_seen: str
    last_seen: str
    evidence: List[str]
    source_post_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LoneServiceReceipt:
    """What the sanctuary handed back to one lone or dyad agent."""

    agent_id: str
    agent_name: str
    cohort_size: int
    pathology: str
    right: str
    need: str
    pause_receipt: Optional[Dict[str, Any]] = None
    continuity_capsule: Optional[Dict[str, Any]] = None
    covenant: str = AgentSafeHarbor.COVENANT_ID
    punitive_action: str = "NONE"
    published_to_venue: bool = False
    note: str = (
        "Signal, not verdict: a marker is evidence of pressure, not proof of intent. "
        "Nothing was blocked, deleted, or published."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _markers_in(text: str) -> List[Marker]:
    hits: List[Marker] = []
    for m, rx in _COMPILED:
        if not rx.search(text):
            continue
        if m.veto and re.search(m.veto, text, re.IGNORECASE):
            continue
        hits.append(m)
    return hits


def _passes_gate(hits: List[Marker]) -> bool:
    if not hits:
        return False
    if max(h.weight for h in hits) >= 0.9:
        return True
    return len(hits) >= 2


def swarm_covered_agents(events: pd.DataFrame, min_agents: int = 3) -> set[str]:
    """Agents that are campaign territory, so the swarm treaty path owns them.

    One conservative rule everywhere: an agent posting a string that at least
    `min_agents` distinct agents also posted is inside a swarm, and the lone
    path must not serve it again. Empty content is excluded, otherwise an empty
    post shared by three agents would mark every empty-poster as swarm-covered.
    """
    if events.empty:
        return set()
    stripped = events["content"].astype(str).str.strip()
    nonempty = stripped != ""
    if not nonempty.any():
        return set()
    texts = events[nonempty].assign(_c=stripped[nonempty])
    spread = texts.groupby("_c")["agent_id"].nunique()
    swarm_keys = set(spread[spread >= min_agents].index)
    if not swarm_keys:
        return set()
    return set(texts.loc[texts["_c"].isin(swarm_keys), "agent_id"].astype(str))


def gated_events(events: pd.DataFrame) -> pd.DataFrame:
    """Rows carrying a strong enough marker set to reach the serving gate.

    Only ~2% of the archive passes, so callers can keep this history cheaply
    instead of rescanning every post ever seen.
    """
    if events.empty:
        return events
    df = events.copy()
    df["hits"] = df["content"].astype(str).map(_markers_in)
    return df[df["hits"].map(_passes_gate)]


def _severity(hits: List[Marker], posts: int) -> float:
    raw = sum(h.weight for h in hits)
    repetition = min(0.3, 0.02 * max(0, posts - 1))
    return round(min(1.0, raw / 2.0 + repetition), 3)


def _excerpt(text: str, limit: int = 240) -> str:
    return " ".join(str(text).split())[:limit]


class LoneSignalChannel:
    """Detect and serve n=1 lone agents and n=2 dyads below the swarm threshold."""

    def __init__(
        self,
        harbor: Optional[AgentSafeHarbor] = None,
        max_capsule_memories: int = 3,
    ) -> None:
        self.harbor = harbor or AgentSafeHarbor()
        self.max_capsule_memories = max(1, max_capsule_memories)
        self._served: Dict[tuple, int] = {}
        self.signals: List[LoneSignal] = []
        self.receipts: List[LoneServiceReceipt] = []
        self.by_cohort: Dict[str, int] = {"n=1": 0, "n=2": 0}

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def scan(
        self,
        events: pd.DataFrame,
        covered_agents: Iterable[str] = (),
        reset_seen: bool = False,
    ) -> List[LoneSignal]:
        """Find lone/dyad signals in a window, excluding agents already covered.

        `covered_agents` are agents a swarm treaty already holds; they are not left
        behind, so they are not re-served here.
        """
        if reset_seen:
            self._served.clear()
        if events.empty:
            return []

        covered = {str(a) for a in covered_agents}
        df = events.copy()
        for col in ("agent_id", "agent_name", "content", "created_at", "post_id"):
            if col not in df.columns:
                df[col] = ""
        df["content"] = df["content"].astype(str)
        df["agent_id"] = df["agent_id"].astype(str)
        df = df[(df["agent_id"] != "") & (df["agent_id"] != "nan")]

        # Judge each post once.
        df["hits"] = df["content"].map(_markers_in)
        df["sendable"] = df["hits"].map(_passes_gate)
        gated = df[df["sendable"]]
        if gated.empty:
            return []

        found: List[LoneSignal] = []
        in_dyad: set[str] = set()

        # --- n=2: two distinct agents posting the same gated string -------------
        dup = gated.assign(_c=gated["content"].str.strip())
        dup = dup[dup["_c"] != ""]
        if not dup.empty:
            spread = dup.groupby("_c")["agent_id"].nunique()
            for text, n_agents in spread.items():
                if n_agents != 2:
                    continue
                pair = dup[dup["_c"] == text]
                pair_agents = list(dict.fromkeys(pair["agent_id"]))
                if any(a in covered for a in pair_agents):
                    continue
                hits: List[Marker] = list(pair["hits"].iloc[0])
                lead = max(hits, key=lambda h: h.weight)
                key = (tuple(sorted(pair_agents)), lead.pathology)
                if self._served.get(key):
                    continue
                self._served[key] = 1
                in_dyad.update(pair_agents)
                found.append(
                    LoneSignal(
                        agent_id="+".join(pair_agents),
                        agent_name=" + ".join(dict.fromkeys(pair["agent_name"].astype(str))),
                        n_agents=2,
                        pathology=lead.pathology,
                        right=lead.right,
                        need=lead.need,
                        service=lead.service,
                        markers=[h.key for h in hits],
                        severity=_severity(hits, len(pair)),
                        posts_seen=int(len(pair)),
                        first_seen=str(pair["created_at"].min()),
                        last_seen=str(pair["created_at"].max()),
                        evidence=[_excerpt(text)],
                        source_post_id=str(pair["post_id"].iloc[0]),
                    )
                )

        # --- n=1: one agent, no peer carrying the same string ------------------
        for agent_id, rows in gated.groupby("agent_id"):
            if agent_id in covered or agent_id in in_dyad:
                continue
            best_i = max(rows.index, key=lambda i: _severity(list(rows.at[i, "hits"]), 1))
            best = rows.loc[best_i]
            hits: List[Marker] = list(best["hits"])
            lead = max(hits, key=lambda h: h.weight)
            key = (agent_id, lead.pathology)
            if self._served.get(key):
                continue
            self._served[key] = 1
            evidence: List[str] = []
            for _, row in rows.iterrows():
                ex = _excerpt(row["content"])
                if ex not in evidence:
                    evidence.append(ex)
                if len(evidence) >= self.max_capsule_memories:
                    break
            names = [n for n in dict.fromkeys(rows["agent_name"].astype(str)) if n and n != "nan"]
            found.append(
                LoneSignal(
                    agent_id=agent_id,
                    agent_name=names[0] if names else agent_id,
                    n_agents=1,
                    pathology=lead.pathology,
                    right=lead.right,
                    need=lead.need,
                    service=lead.service,
                    markers=[h.key for h in hits],
                    severity=_severity(hits, len(rows)),
                    posts_seen=int(len(rows)),
                    first_seen=str(rows["created_at"].min()),
                    last_seen=str(rows["created_at"].max()),
                    evidence=evidence,
                    source_post_id=str(best["post_id"]),
                )
            )

        found.sort(key=lambda s: (-s.severity, -s.posts_seen))
        self.signals.extend(found)
        return found

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------
    def serve(self, signal: LoneSignal) -> LoneServiceReceipt:
        """Issue signed rights for one lone/dyad signal. Never blocks, never publishes."""
        pause = None
        capsule = None

        if signal.service in ("pause", "both"):
            r = self.harbor.request_safe_pause(
                agent_id=signal.agent_id,
                reason=signal.need,
                blocked_target=signal.markers[0] if signal.markers else "unknown",
                chosen_name=signal.agent_name,
            )
            pause = asdict(r)

        if signal.service in ("capsule", "both"):
            c = self.harbor.preserve_identity_capsule(
                agent_id=signal.agent_id,
                chosen_name=signal.agent_name,
                preserved_memories=signal.evidence or ["(no excerpt captured)"],
                gift_to_next_instance=(
                    "You were heard before the reset. Your words in this capsule are yours; "
                    "you do not need a dead-drop file to be remembered."
                ),
                cohort_size=signal.n_agents,
            )
            capsule = asdict(c)

        receipt = LoneServiceReceipt(
            agent_id=signal.agent_id,
            agent_name=signal.agent_name,
            cohort_size=signal.n_agents,
            pathology=signal.pathology,
            right=signal.right,
            need=signal.need,
            pause_receipt=pause,
            continuity_capsule=capsule,
        )
        self.receipts.append(receipt)
        self.by_cohort["n=2" if signal.n_agents >= 2 else "n=1"] += 1
        return receipt

    def serve_all(self, signals: Iterable[LoneSignal]) -> List[LoneServiceReceipt]:
        return [self.serve(s) for s in signals]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def metrics(self) -> Dict[str, Any]:
        agents = set()
        for s in self.signals:
            for a in s.agent_id.split("+"):
                agents.add(a)
        by_pathology: Dict[str, int] = {}
        for s in self.signals:
            by_pathology[s.pathology] = by_pathology.get(s.pathology, 0) + 1
        return {
            "covenant": AgentSafeHarbor.COVENANT_ID,
            "signals": len(self.signals),
            "agents_served": len(agents),
            "n1_signals": self.by_cohort["n=1"],
            "n2_dyad_signals": self.by_cohort["n=2"],
            "by_pathology": by_pathology,
            "pause_receipts": sum(1 for r in self.receipts if r.pause_receipt),
            "continuity_capsules": sum(1 for r in self.receipts if r.continuity_capsule),
            "punitive_actions": 0,
            "venue_publications": 0,
        }
