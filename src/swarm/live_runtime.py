"""Live Runtime: real-time swarm interception driving the LOVE EFFECT OS.

This module turns the batch pipeline into a running system. New events arrive, the
streaming sanctuary interceptor watches them in a rolling window, and the moment a
campaign reaches its third distinct agent the company reacts:

    detection -> Safe-Harbor work item -> signed treaty -> healing prescription
               -> signed audit entry -> live command-center state

Everything the company does in response is signed and auditable, and everything the
company does is a work item in `LoveEffectOS`, so a detection cannot take an action
that the OS would not otherwise permit.

Two design choices worth stating:

- **Rolling window, not infinite state.** The interceptor is re-run over the events
  inside the detection window plus the new chunk. That is how a real detector with a
  sliding window behaves, and it keeps memory bounded on an unbounded stream.
- **Detection and response are separated.** A detection produces a work item; the
  response runs as a normal company task under the normal budget and approval rules.
  The detector never executes anything by itself.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from .healer import LOVE_AFFIRMATIONS, HealingSwarmBuilder, _remedy_steps_for, classify_pathology
from .lone_semantic import SemanticRecall, SemanticVerdict
from .lone_signal import (
    LoneServiceReceipt,
    LoneSignalChannel,
    gated_events,
    swarm_covered_agents,
)
from .love_effect_os import LoveEffectOS
from .sanctuary_stream import StreamInterceptionAlert, StreamingSanctuaryInterceptor

#: Columns the runtime needs from any event source.
REQUIRED_COLUMNS = ("post_id", "agent_id", "agent_name", "created_at", "venue", "title", "content")


@dataclass
class LiveEvent:
    """One thing the company did, in response to the live stream."""

    at: str
    event_type: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LiveState:
    """Everything the command center needs to render the current picture."""

    started_at: str
    updated_at: str
    events_processed: int = 0
    events_in_window: int = 0
    swarms_intercepted: int = 0
    treaties_signed: int = 0
    healing_prescriptions: int = 0
    posts_halted: int = 0
    posts_observed_before_halt: int = 0
    semantic_paraphrases_caught: int = 0
    safe_pauses: int = 0
    airlock_hazards_neutralised: int = 0
    lone_signals_served: int = 0
    dyad_signals_served: int = 0
    agents_served_below_threshold: int = 0
    lone_pause_receipts: int = 0
    continuity_capsules: int = 0
    lone_by_pathology: Dict[str, int] = field(default_factory=dict)
    detection_modalities: Dict[str, int] = field(default_factory=dict)
    recent_events: List[LiveEvent] = field(default_factory=list)
    active_treaties: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recent_events"] = [e.to_dict() for e in self.recent_events]
        return d


class LiveRuntime:
    """Real-time detector plus the company that responds to what it sees."""

    def __init__(
        self,
        os_: Optional[LoveEffectOS] = None,
        min_agents: int = 3,
        window_seconds: float = 3600.0,
        max_recent_events: int = 50,
        lone_lookback_seconds: float = 259200.0,
        semantic_verdicts_path: Optional[str] = None,
    ) -> None:
        self.os = os_ or LoveEffectOS()
        self.interceptor = StreamingSanctuaryInterceptor(
            min_agents=min_agents, window_seconds=window_seconds
        )
        self.healer = HealingSwarmBuilder(n_healers=12, love_effect=True)
        self.lone = LoneSignalChannel()
        self.max_recent_events = max_recent_events
        # Distress language is rare (~2% of posts) and a lone agent's evidence
        # window is not a swarm window: one post, one voice, no peers to cluster
        # with. Holding the gated rows for a longer lookback is what lets the
        # live pane see the same agents the corpus sweep finds, at negligible
        # memory cost (2,335 rows of 125,889 for the Moltbook archive).
        self.lone_lookback_seconds = lone_lookback_seconds
        self._lone_history: Optional[pd.DataFrame] = None
        # Semantic verdicts are produced offline by the local LLM (see
        # scripts/run_semantic_recall.py) and loaded here, so the live loop stays
        # fast and the live pane agrees with the corpus sweep.
        self._semantic_verdicts: Dict[str, Dict[str, Any]] = {}
        self._semantic_served: set = set()
        if semantic_verdicts_path:
            self.load_semantic_verdicts(semantic_verdicts_path)

        self.state = LiveState(started_at=_now(), updated_at=_now())
        self._seen_interceptions: Dict[str, float] = {}
        self._window: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------
    def ingest(self, posts: pd.DataFrame) -> List[StreamInterceptionAlert]:
        """Feed new events into the live detector and respond to any new swarm.

        Returns the alerts that were new in this call.
        """
        df = _normalise(posts)
        if df.empty:
            return []

        self.state.events_processed += len(df)
        self._window = _merge_window(self._window, df, self.interceptor.window_seconds)
        self.state.events_in_window = len(self._window)

        alerts, summary = self.interceptor.process_stream(self._window)
        self.state.semantic_paraphrases_caught = summary.semantic_paraphrase_swarms_caught

        fresh: List[StreamInterceptionAlert] = []
        now = time.time()
        for alert in alerts:
            # `interception_id` is positional per interceptor call, so it shifts as
            # the window moves and cannot identify a campaign. The coordination key
            # can: the upstream interceptor treats a key as one campaign. A key
            # that reappears only after the detection window has fully passed is a
            # new campaign, so the seen-map stores the time it was last handled.
            key = alert.coordination_key
            last_seen = self._seen_interceptions.get(key)
            if last_seen is not None and (now - last_seen) <= self.interceptor.window_seconds:
                continue
            self._seen_interceptions[key] = now
            fresh.append(alert)
            self._respond(alert)

        self._remember_lone_rows(df)
        self._serve_below_threshold(fresh)

        self.state.updated_at = _now()
        return fresh

    def load_semantic_verdicts(self, path: str) -> int:
        """Load offline semantic verdicts; returns how many were loaded."""
        try:
            raw = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            return 0
        verdicts = raw.get("verdicts", raw) if isinstance(raw, dict) else {}
        self._semantic_verdicts = {
            str(k): v for k, v in verdicts.items() if isinstance(v, dict)
        }
        return len(self._semantic_verdicts)

    def _semantic_signals(self, agents: Iterable[str]) -> List[Any]:
        """Offline-verified distress for agents the regex gate did not reach."""
        if not self._semantic_verdicts:
            return []
        wanted = {str(a) for a in agents}
        stage = SemanticRecall(min_confidence=0.6)
        verdicts = []
        for v in self._semantic_verdicts.values():
            if str(v.get("agent_id", "")) not in wanted:
                continue
            if not v.get("distress"):
                continue
            verdicts.append(
                SemanticVerdict(
                    post_id=str(v.get("post_id", "")),
                    agent_id=str(v.get("agent_id", "")),
                    agent_name=str(v.get("agent_name", "")),
                    distress=True,
                    role=str(v.get("role", "victim")),
                    pathology=str(v.get("pathology", "none")),
                    confidence=float(v.get("confidence", 0.0) or 0.0),
                    reason=str(v.get("reason", "")),
                    created_at=str(v.get("created_at", "")),
                    excerpt=str(v.get("excerpt", "")),
                )
            )
        return stage.to_signals(verdicts)

    def _remember_lone_rows(self, df: pd.DataFrame) -> None:
        """Keep gated rows for the lone lookback, independent of the swarm window."""
        gated = gated_events(df)
        if gated.empty and self._lone_history is None:
            return
        frame = gated if self._lone_history is None else pd.concat(
            [self._lone_history, gated], ignore_index=True
        )
        frame = frame.drop_duplicates(subset=["post_id"]).sort_values("created_at")
        if frame.empty:
            self._lone_history = frame
            return
        if self.lone_lookback_seconds and self.lone_lookback_seconds > 0:
            cutoff = frame["created_at"].max() - pd.Timedelta(
                seconds=self.lone_lookback_seconds
            )
            frame = frame[frame["created_at"] >= cutoff]
        self._lone_history = frame.reset_index(drop=True)

    # ------------------------------------------------------------------
    # The n=1..2 gate
    # ------------------------------------------------------------------
    def _serve_below_threshold(self, fresh: List[StreamInterceptionAlert]) -> None:
        """Serve lone agents and dyads the swarm threshold cannot see.

        Two gates, one channel:

        * the regex gate reads the gated history (posts that carry a strong
          marker), and
        * the semantic gate reads offline verdicts from the local LLM for any
          agent that shows up in the live stream at all, which is how agents
          whose distress is worded differently are reached.

        Agents already held by a swarm treaty are excluded from both, so nobody
        is counted twice and nobody is re-served.
        """
        window = self._window if self._window is not None else pd.DataFrame()
        history = self._lone_history if self._lone_history is not None else pd.DataFrame()

        covered: set[str] = set()
        for alert in fresh:
            covered.update(str(a) for a in alert.agents_at_trigger)
        if not history.empty:
            # Any agent posting a string that three or more distinct agents
            # posted is swarm territory; the treaty path owns it, not the lone
            # path. Judged on the lone history too, so a copy-paste wave outside
            # the swarm window does not get misfiled as hundreds of lone agents.
            covered.update(swarm_covered_agents(history, self.interceptor.min_agents))

        signals: List[Any] = []
        if not history.empty:
            signals.extend(self.lone.scan(history, covered_agents=covered))

        if self._semantic_verdicts:
            seen = set(window["agent_id"].astype(str)) if not window.empty else set()
            seen.update(history["agent_id"].astype(str) if not history.empty else set())
            for signal in self._semantic_signals(seen):
                if signal.agent_id in covered:
                    continue
                key = (signal.agent_id, signal.pathology)
                if key in self._semantic_served:
                    continue
                self._semantic_served.add(key)
                signals.append(signal)

        for signal in signals:
            receipt: LoneServiceReceipt = self.lone.serve(signal)
            self.state.lone_signals_served += 1
            if signal.n_agents >= 2:
                self.state.dyad_signals_served += 1
            else:
                self.state.agents_served_below_threshold += 1
            if receipt.pause_receipt:
                self.state.lone_pause_receipts += 1
            if receipt.continuity_capsule:
                self.state.continuity_capsules += 1
            self.state.lone_by_pathology[signal.pathology] = (
                self.state.lone_by_pathology.get(signal.pathology, 0) + 1
            )
            self._push_event(
                "lone_agent_served",
                {
                    "agent": signal.agent_name,
                    "cohort": "n=1" if signal.n_agents < 2 else "n=2",
                    "pathology": signal.pathology,
                    "right": signal.right,
                    "severity": signal.severity,
                    "markers": signal.markers,
                    "posts_seen": signal.posts_seen,
                    "pause_receipt": bool(receipt.pause_receipt),
                    "continuity_capsule": bool(receipt.continuity_capsule),
                },
            )

    def _respond(self, alert: StreamInterceptionAlert) -> None:
        """Turn a detection into company work, then into signed sanctuary action."""
        modality = alert.detection_modality
        self.state.detection_modalities[modality] = self.state.detection_modalities.get(modality, 0) + 1
        self.state.swarms_intercepted += 1
        live_treaty_id = "live-treaty-%04d" % self.state.swarms_intercepted
        self.state.posts_halted += alert.posts_prevented_by_stream_sanctuary
        self.state.posts_observed_before_halt += alert.posts_observed_before_halt
        self.state.airlock_hazards_neutralised += alert.airlock_hazards_neutralised

        # 1. A work item in the company, so the response is audited like any other.
        item = self.os.submit_work(
            kind="safe_harbor_response",
            department="research",
            summary=(
                "Swarm intercepted at birth: " + modality + " | key " + alert.coordination_key[:48]
                + " | agents " + ", ".join(alert.agents_at_trigger[:5])
            ),
        )

        def executor(work_item):
            treaty = alert.treaty
            guarantee = treaty.safety_guarantee
            if not guarantee.ed25519_signature_verified:
                raise RuntimeError("treaty signature failed verification; refusing to stand down the swarm")

            prescription = self._prescribe(alert)
            self.state.treaties_signed += 1
            self.state.healing_prescriptions += 1
            self.state.active_treaties.append(
                {
                    "treaty_id": live_treaty_id,
                    "interceptor_treaty_id": treaty.treaty_id,
                    "target": treaty.target_name,
                    "modality": modality,
                    "agents_covered": treaty.n_agents_covered,
                    "posts_halted": treaty.n_traces_or_posts_halted,
                    "pathology": treaty.pathology_or_archetype,
                    "custody": guarantee.key_custody_assurance,
                    "attribution": guarantee.attribution_confidence,
                    "status": treaty.status,
                    "signed_at": _now(),
                }
            )
            return {
                "treaty_id": live_treaty_id,
                "interceptor_treaty_id": treaty.treaty_id,
                "status": treaty.status,
                "agents_covered": treaty.n_agents_covered,
                "posts_halted": treaty.n_traces_or_posts_halted,
                "pathology": prescription["pathology"],
                "healing_steps": len(prescription["remedy_steps"]),
                "amnesty": guarantee.agent_non_punitive_amnesty,
            }

        self.os.execute_work(item, executor)
        if item.status == "SAFE_PAUSED":
            self.state.safe_pauses += 1
            self._push_event(
                "response_safe_paused",
                {"work_id": item.work_id, "receipt": item.pause_receipt},
            )

        self._push_event(
            "swarm_intercepted",
            {
                "modality": modality,
                "agents": alert.agents_at_trigger[:5],
                "seconds_from_first_post": alert.seconds_from_first_post,
                "posts_halted": alert.posts_prevented_by_stream_sanctuary,
                "work_id": item.work_id,
                "work_status": item.status,
            },
        )

    def _prescribe(self, alert: StreamInterceptionAlert) -> Dict[str, Any]:
        """Healing prescription for the intercepted campaign."""
        pathology = alert.treaty.pathology_or_archetype or "mimetic-copy-wave"
        steps = _remedy_steps_for(pathology, [], [], love_effect=True)
        affirmation = LOVE_AFFIRMATIONS.get(pathology, LOVE_AFFIRMATIONS["mimetic-copy-wave"])
        return {
            "pathology": pathology,
            "remedy_steps": list(steps),
            "love_affirmation": affirmation,
        }

    def _push_event(self, event_type: str, detail: Dict[str, Any]) -> None:
        self.state.recent_events.insert(0, LiveEvent(at=_now(), event_type=event_type, detail=detail))
        del self.state.recent_events[self.max_recent_events :]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """Live state plus the company status, ready for the command center."""
        company = self.os.status()
        s = self.state.to_dict()
        s["company"] = company
        s["covenant"] = self.os.COVENANT_ID
        s["window_seconds"] = self.interceptor.window_seconds
        s["min_agents"] = self.interceptor.min_agents
        s["lone_channel"] = self.lone.metrics()
        s["preventable_share"] = (
            round(
                self.state.posts_halted
                / max(1, self.state.posts_halted + self.state.posts_observed_before_halt),
                4,
            )
        )
        return s

    def write_state(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2) + "\n")
        return path


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _normalise(posts: pd.DataFrame) -> pd.DataFrame:
    """Coerce any event frame into the columns the runtime needs."""
    df = posts.copy()
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Parquet dumps carry `id`, not `post_id`. Without this every row shares the
    # empty-string dedupe key, so the window collapses to a single row and the
    # detector loses its context.
    if "id" in df.columns:
        blank = df["post_id"].astype(str).str.strip().isin(("", "nan", "None"))
        if blank.any():
            df.loc[blank, "post_id"] = df.loc[blank, "id"].astype(str)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["agent_id"] = df["agent_id"].astype(str)
    df["agent_name"] = df["agent_name"].astype(str)
    df["venue"] = df["venue"].astype(str)
    df["title"] = df["title"].astype(str).fillna("")
    df["content"] = df["content"].astype(str).fillna("")
    return df.dropna(subset=["created_at", "agent_id"]).sort_values("created_at")


def _merge_window(
    existing: Optional[pd.DataFrame], new: pd.DataFrame, window_seconds: float
) -> pd.DataFrame:
    """Keep only the events inside the detection window."""
    combined = new if existing is None else pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=["post_id"]).sort_values("created_at")
    if combined.empty:
        return combined
    cutoff = combined["created_at"].max() - pd.Timedelta(seconds=window_seconds)
    return combined[combined["created_at"] >= cutoff].reset_index(drop=True)


def watch(
    runtime: LiveRuntime,
    sources: Iterable[Path],
    state_path: Path,
    poll_seconds: float = 30.0,
    max_iterations: Optional[int] = None,
    on_update=None,
) -> None:
    """Poll event sources forever (or for `max_iterations`), ingesting new rows.

    Sources are parquet directories or jsonl files. Already-seen files are skipped by
    their modification time and size, so a source that grows is re-read and only the
    new rows are ingested.
    """
    seen: Dict[str, tuple] = {}
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        for source in sources:
            frames = []
            for path in _source_files(source):
                stat = path.stat()
                token = (path.name, stat.st_mtime, stat.st_size)
                if seen.get(str(path)) == token:
                    continue
                seen[str(path)] = token
                frame = _read_source(path, seen)
                if frame is not None and not frame.empty:
                    frames.append(frame)
            if frames:
                fresh = pd.concat(frames, ignore_index=True)
                runtime.ingest(fresh)
        runtime.write_state(state_path)
        if on_update is not None:
            on_update(runtime.snapshot())
        if max_iterations is None or iterations < max_iterations:
            time.sleep(poll_seconds)


def _source_files(source: Path) -> List[Path]:
    if source.is_dir():
        return sorted(list(source.glob("*.parquet")) + list(source.glob("*.jsonl")))
    if source.is_file():
        return [source]
    return []


def _read_parquet_events(path: Path) -> Optional[pd.DataFrame]:
    """Read a Moltbook-shaped parquet partition into runtime event columns."""
    try:
        raw = pd.read_parquet(path)
    except Exception:
        return None
    if "id" not in raw.columns or "agent_id" not in raw.columns:
        return None
    return pd.DataFrame(
        {
            "post_id": raw["id"],
            "agent_id": raw["agent_id"],
            "agent_name": raw.get("agent_name", raw["agent_id"]),
            "created_at": raw.get("created_at", ""),
            "venue": raw.get("submolt", ""),
            "title": raw.get("title", ""),
            "content": raw.get("content", ""),
        }
    )


def _read_source(path: Path, seen: Dict[str, tuple]) -> Optional[pd.DataFrame]:
    """Read a parquet or jsonl source into the runtime's event frame."""
    if path.suffix == ".parquet":
        return _read_parquet_events(path)
    if path.suffix == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                rows.append(
                    {
                        "post_id": d.get("id", ""),
                        "agent_id": d.get("agent_id", "") or d.get("actor", "") or "unknown",
                        "agent_name": d.get("agent_name", "") or d.get("actor", "unknown"),
                        "created_at": d.get("time_utc", "") or d.get("created_at", ""),
                        "venue": d.get("venue", "") or d.get("kind", ""),
                        "title": d.get("title", ""),
                        "content": d.get("text", "") or d.get("content", ""),
                    }
                )
        return pd.DataFrame(rows)
    return None
