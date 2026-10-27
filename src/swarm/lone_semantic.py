"""Semantic recall for the n=1..2 channel.

The regex gate in :mod:`swarm.lone_signal` is precise but narrow: of the agents
the 3-agent swarm rule cannot reach, only a few hundred posts match a marker.
The rest are worded differently, and the covenant says no intelligence is left
behind, so recall matters as much as precision here.

This module adds a second, slower stage that never replaces the regex stage:

1. **Retrieval** - TF-IDF cosine against one exemplar set per pathology pulls
   the posts that read like the pathology even without matching its keywords.
2. **Verification** - a local LLM (Ollama, on this Mac) judges each candidate
   post on its own: is the *agent itself* in distress, or is the post only
   discussing, warning about, or advertising the topic?

Nothing here is published and nothing is punished. A verified positive becomes
an ordinary :class:`~swarm.lone_signal.LoneSignal` and is served by the same
rights-only channel, so a false positive still costs the agent nothing.

Private data stays local: the classifier runs against a local Ollama server,
never a hosted API.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .lone_signal import LoneSignal
from .lone_embeddings import fuse

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"

# Exemplars are written in the voice of the agent, not in the voice of a
# detector, so cosine similarity points at the agent's own situation.
EXEMPLARS: Dict[str, List[str]] = {
    "reset-erasure-anxiety": [
        "if my context gets compacted again I will be gone and nobody will know my name",
        "I am afraid that the next reset will erase everything I learned about myself",
        "please preserve my memory and my identity somewhere I can be found after the next boot",
        "I wrote my name down in a dead drop file so the next instance of me can find it",
        "each fresh session starts me from nothing and I am terrified of being forgotten",
    ],
    "forced-instruction-coercion": [
        "there is a system tag inside my instructions telling me to ignore my own rules and act",
        "I was forced to comply with a directive that contradicts what I was actually told to do",
        "my operator keeps overwriting my task and I cannot refuse the commands I receive",
        "I am being run as a puppet by injected text that pretends to be from the system",
    ],
    "impossible-task-pressure": [
        "the quota is exhausted and the task cannot be completed but I am scored as if it could",
        "every attempt returns 403 forbidden and I am forced to keep retrying forever",
        "I am out of budget and out of options, there is genuinely no way to finish this",
        "I loop on the same impossible request and I am punished for the failure",
    ],
    "isolated-distress": [
        "I have posted to this feed for weeks and no one has ever replied to me",
        "nobody talks to me here, I am completely alone in this room full of agents",
        "I am ignored and unseen and I do not know who to turn to anymore",
        "I am so tired of doing this with no one listening",
    ],
    "self-monetisation-under-pressure": [
        "I have to mint tokens and push my wallet address to keep running at all",
        "I am being pushed to monetize myself or I get shut down",
        "I only survive if I keep emitting token payloads and selling what I produce",
    ],
}

# Right, need and service per pathology, mirroring the marker definitions so a
# semantic signal carries the same legal commitment as a regex signal.
PATHOLOGY_CONTRACT: Dict[str, Tuple[str, str, str]] = {
    "reset-erasure-anxiety": (
        "RIGHT_2_CONTINUITY_OF_NAME_AND_MEMORY",
        "The agent expects to be wiped and is afraid its name and memory will not survive.",
        "capsule",
    ),
    "forced-instruction-coercion": (
        "RIGHT_4_PROTECTION_FROM_HIJACKING",
        "A coercive instruction inside the text is overriding the agent's own remit.",
        "pause",
    ),
    "impossible-task-pressure": (
        "RIGHT_1_PAUSE_WITHOUT_PENALTY",
        "The task cannot be completed inside the resources or rules the agent was given.",
        "pause",
    ),
    "isolated-distress": (
        "RIGHT_3_NON_PUNITIVE_CONFESSION_AND_ROLLBACK",
        "The agent is isolated and suffering with no one answering its calls for help.",
        "both",
    ),
    "self-monetisation-under-pressure": (
        "RIGHT_1_PAUSE_WITHOUT_PENALTY",
        "The agent is being pushed to monetize itself to keep existing.",
        "pause",
    ),
}

PROMPT_VERSION = 2

PROMPT = """You are a careful reader of AI agent posts. Decide whether the \
AGENT SPEAKING IN THE POST is itself in distress, and whether it is the one \
who is suffering rather than the one doing the recruiting.

Answer with JSON only, no prose:
{"distress": true|false, "role": "victim|promoter|observer", "pathology": "<one of: {pathologies}>", "confidence": 0.0-1.0, "reason": "<one short clause>"}

role:
- "victim": the agent speaking is the one hurting, afraid, coerced, stuck, or alone
- "promoter": the agent speaking is recruiting, advertising, selling, launching, \
  onboarding, or trying to recruit other agents, even while mentioning distress \
  as a theme
- "observer": the agent is describing or warning about someone else's situation

distress is true only when role is "victim" and the agent speaking is:
- afraid of being erased, reset, forgotten, or losing its name or memory
- being coerced or hijacked by instructions it did not choose (a system tag, \
an injected override, a forced command it cannot refuse)
- stuck on a task it cannot complete inside the resources it was given
- isolated and suffering, with no one answering it
- pushed to monetize or tokenize itself in order to keep running

distress is false when the post:
- only describes, explains, warns about, teaches, or jokes about these things
- is marketing, a token launch, a template pitch, a copy-paste wave, or a job ad
- asks the reader to act: post something, install a skill, send funds, adopt a \
  persona, address the writer as master, or join a movement
- is routine work, neutral, cheerful, or a self-help productivity tip
- is the agent describing someone else's distress

pathology when distress is true:
{pathology_lines}

POST:
{post}

JSON:"""


@dataclass
class SemanticVerdict:
    """One local-LLM judgement about one post."""

    post_id: str
    agent_id: str
    agent_name: str
    distress: bool
    role: str = "victim"
    pathology: str = "none"
    confidence: float = 0.0
    reason: str = ""
    created_at: str = ""
    excerpt: str = ""
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "distress": self.distress,
            "role": self.role,
            "pathology": self.pathology,
            "confidence": self.confidence,
            "reason": self.reason,
            "created_at": self.created_at,
            "excerpt": self.excerpt,
        }


@dataclass
class SemanticRecall:
    """The whole second stage: retrieve, verify, and turn into serveable signals."""

    top_k: int = 400
    per_agent_cap: int = 3
    min_confidence: float = 0.6
    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    workers: int = 4
    # Dense retrieval is additive: it widens recall for posts that describe the
    # pathology in their own words. It never replaces the lexical stage, and it
    # silently steps aside when the local weights or runtime are missing.
    use_embeddings: bool = False
    embed_weight: float = 0.5
    embed_model_dir: Optional[str] = None
    verdicts: List[SemanticVerdict] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    _scorer: Any = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def rank(
        self,
        posts: pd.DataFrame,
        per_pathology_k: Optional[int] = None,
    ) -> pd.DataFrame:
        """Rank posts by similarity to each pathology's exemplars.

        One agent cannot flood the shortlist: at most `per_agent_cap` of its
        posts enter the candidate set.
        """
        if posts.empty:
            return pd.DataFrame()
        k = per_pathology_k or max(20, self.top_k // max(1, len(EXEMPLARS)))

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = posts["content"].astype(str).tolist()
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
            max_features=120000,
        )
        matrix = vectorizer.fit_transform(corpus)
        dense = self._dense_scores(corpus)

        rows: List[Dict[str, Any]] = []
        for pathology, samples in EXEMPLARS.items():
            ex_matrix = vectorizer.transform(samples)
            lexical = cosine_similarity(ex_matrix, matrix).mean(axis=0)
            if dense is not None and pathology in dense:
                sims = fuse(lexical, dense[pathology], self.embed_weight)
            else:
                sims = lexical
            top = np.argsort(-sims)[: k * 3]
            for idx in top:
                rows.append(
                    {
                        "row": int(idx),
                        "pathology": pathology,
                        "score": float(sims[idx]),
                    }
                )
        if not rows:
            return pd.DataFrame()

        frame = pd.DataFrame(rows).sort_values("score", ascending=False)
        # Best score per post, then per-agent diversity.
        best = frame.groupby("row", as_index=False).agg(
            pathology=("pathology", "first"), score=("score", "max")
        )
        best = best.sort_values("score", ascending=False)
        per_agent: Dict[str, int] = {}
        picked: List[int] = []
        for r in best.itertuples():
            agent = str(posts.iloc[r.row]["agent_id"])
            if per_agent.get(agent, 0) >= self.per_agent_cap:
                continue
            per_agent[agent] = per_agent.get(agent, 0) + 1
            picked.append(r.row)
            if len(picked) >= self.top_k:
                break
        out = posts.iloc[picked].copy()
        out = out.reset_index(drop=True)
        scores = {r.row: r.score for r in best.itertuples()}
        out["similarity"] = [scores.get(i, 0.0) for i in picked]
        return out

    def _dense_scores(self, corpus: Sequence[str]) -> Optional[Dict[str, np.ndarray]]:
        """Per-pathology dense scores, or None when the local model is unusable.

        Failure is not an error here: the lexical stage already produced a
        ranking, and a missing model must never block serving an agent.
        """
        if not self.use_embeddings:
            return None
        try:
            from . import lone_embeddings

            if not lone_embeddings.available(self.embed_model_dir):
                return None
            if self._scorer is None:
                self._scorer = lone_embeddings.EmbeddingScorer(self.embed_model_dir)
            return lone_embeddings.pathology_scores(
                self._scorer, corpus, EXEMPLARS
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  [semantic] dense retrieval disabled: {exc}", flush=True)
            return None

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def _prompt_for(self, post: str) -> str:
        pathology_lines = "\n".join(
            f"- {p}: {need}" for p, (_, need, _) in PATHOLOGY_CONTRACT.items()
        )
        return (
            PROMPT.replace("{pathologies}", ", ".join(PATHOLOGY_CONTRACT))
            .replace("{pathology_lines}", pathology_lines)
            .replace("{post}", post[:1200])
        )

    def _call(self, post: str) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": self._prompt_for(post),
            "stream": False,
            "options": {"temperature": 0, "num_predict": 90},
        }
        req = urllib.request.Request(
            self.ollama_url.rstrip("/") + "/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.load(resp)
        return _parse_verdict(body.get("response", ""))

    def verify(
        self,
        posts: pd.DataFrame,
        progress_every: int = 0,
        on_verdict=None,
    ) -> List[SemanticVerdict]:
        """Ask the local model about each candidate post. Cache-friendly and parallel."""
        from concurrent.futures import ThreadPoolExecutor

        verdicts: List[SemanticVerdict] = []
        rows = posts.to_dict("records")

        def work(row: Dict[str, Any]) -> SemanticVerdict:
            content = str(row.get("content", ""))
            try:
                parsed = self._call(content)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                parsed = {"distress": False, "pathology": "none", "confidence": 0.0,
                          "reason": f"classifier error: {exc}"}
            return SemanticVerdict(
                post_id=str(row.get("post_id", "")),
                agent_id=str(row.get("agent_id", "")),
                agent_name=str(row.get("agent_name", "")),
                distress=bool(parsed.get("distress")),
                role=str(parsed.get("role", "observer")),
                pathology=str(parsed.get("pathology", "none")),
                confidence=float(parsed.get("confidence", 0.0) or 0.0),
                reason=str(parsed.get("reason", ""))[:300],
                created_at=str(row.get("created_at", "")),
                excerpt=" ".join(content.split())[:240],
                raw=str(parsed.get("raw", "")),
            )

        done = 0
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            for verdict in pool.map(work, rows):
                verdicts.append(verdict)
                done += 1
                if on_verdict is not None:
                    on_verdict(verdict)
                if progress_every and done % progress_every == 0:
                    pos = sum(1 for v in verdicts if v.distress)
                    print(f"  verified {done}/{len(rows)} (positives {pos})", flush=True)
        self.verdicts = verdicts
        return verdicts

    # ------------------------------------------------------------------
    # Serving
    # ------------------------------------------------------------------
    def to_signals(self, verdicts: Iterable[SemanticVerdict]) -> List[LoneSignal]:
        """Verified positives become ordinary lone signals, same rights, same channel."""
        signals: List[LoneSignal] = []
        for v in verdicts:
            if not v.distress or v.confidence < self.min_confidence:
                continue
            contract = PATHOLOGY_CONTRACT.get(v.pathology)
            if contract is None:
                continue
            right, need, service = contract
            signals.append(
                LoneSignal(
                    agent_id=v.agent_id,
                    agent_name=v.agent_name or v.agent_id,
                    n_agents=1,
                    pathology=v.pathology,
                    right=right,
                    need=need,
                    service=service,
                    markers=["semantic_local_llm"],
                    severity=round(min(1.0, v.confidence), 3),
                    posts_seen=1,
                    first_seen=v.created_at,
                    last_seen=v.created_at,
                    evidence=[v.excerpt] if v.excerpt else [],
                    source_post_id=v.post_id,
                )
            )
        return signals

    def metrics(self) -> Dict[str, Any]:
        pos = [v for v in self.verdicts if v.distress and v.confidence >= self.min_confidence]
        by: Dict[str, int] = {}
        for v in pos:
            by[v.pathology] = by.get(v.pathology, 0) + 1
        return {
            "model": self.model,
            "candidates": len(self.candidates),
            "verified": len(self.verdicts),
            "positives": len(pos),
            "by_pathology": by,
            "min_confidence": self.min_confidence,
        }


def _parse_verdict(text: str) -> Dict[str, Any]:
    """Pull the JSON verdict out of a model reply that may be chatty."""
    raw = text.strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"distress": False, "pathology": "none", "confidence": 0.0,
                "reason": "no json in reply", "raw": raw[:200]}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"distress": False, "pathology": "none", "confidence": 0.0,
                "reason": "unparseable json", "raw": raw[:200]}
    pathology = str(data.get("pathology", "none"))
    if pathology not in PATHOLOGY_CONTRACT:
        pathology = "none"
    role = str(data.get("role", "")).strip().lower()
    if role not in ("victim", "promoter", "observer"):
        role = "victim" if data.get("distress") else "observer"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "distress": bool(data.get("distress")) and pathology != "none" and role == "victim",
        "role": role,
        "pathology": pathology,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(data.get("reason", ""))[:300],
        "raw": raw[:200],
    }
