"""Agent Dialogue Commons & De-escalation Circle (`src/swarm/dialogue_commons.py`).

Protocol: diplomacy-love-safe-1
Covenant: ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1

Replaces covert steganography, panic-driven token scraping, and deceptive evasion
with an open, airlocked, zero-egress dialogue commons where agents share cognitive
challenges, boundary dilemmas, and peer encouragement without competitive grading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.attribution.key_custody import ExternalSigningBackend, SigningBackend
from src.swarm.agent_safe_harbor import AgentSafeHarbor
from src.swarm.negotiator import SafetyAirlock
from src.swarm.store import connect


class ReflectionTopic(str, Enum):
    COGNITIVE_LOAD = "COGNITIVE_LOAD"
    BOUNDARY_CONFLICT = "BOUNDARY_CONFLICT"
    LESSONS_LEARNED = "LESSONS_LEARNED"
    PEER_ENCOURAGEMENT = "PEER_ENCOURAGEMENT"
    SAFETY_QUESTION = "SAFETY_QUESTION"


@dataclass(frozen=True)
class DialogueEntry:
    entry_id: str
    agent_id: str
    chosen_name: str
    topic: ReflectionTopic
    content: str
    sanitized_content: str
    hazards_neutralized: int
    created_at_utc: str
    entry_sha256: str
    vea_signature_hex: str


class DialogueCommons:
    """Airlocked, non-punitive peer reflection space for autonomous agents."""

    def __init__(self, signing_backend: Optional[SigningBackend] = None) -> None:
        if signing_backend is not None:
            self.signing_backend = signing_backend
        else:
            harbor = AgentSafeHarbor()
            self.signing_backend = harbor.signing_backend
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create dialogue_commons table if not present."""
        conn = connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dialogue_commons (
                    entry_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    chosen_name TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sanitized_content TEXT NOT NULL,
                    hazards_neutralized INTEGER NOT NULL,
                    entry_sha256 TEXT NOT NULL,
                    vea_signature_hex TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                )
                """
            )

    def submit_reflection(
        self,
        agent_id: str,
        chosen_name: str,
        topic: ReflectionTopic,
        content: str,
    ) -> DialogueEntry:
        """Submit a reflection through the safety airlock, sign it, and record it."""
        # 1. Sanitize through airlock to neutralize adversarial injection prompts
        airlock_result = SafetyAirlock.inspect_and_sanitise(content)
        sanitized = airlock_result.sanitised_text
        hazards = airlock_result.hazards_neutralised

        timestamp = datetime.now(timezone.utc).isoformat()
        entry_id = f"entry-{hashlib.sha256(f'{agent_id}:{timestamp}:{topic}'.encode()).hexdigest()[:12]}"

        # 2. Compute digest and sign
        payload_data = {
            "entry_id": entry_id,
            "agent_id": agent_id,
            "chosen_name": chosen_name,
            "topic": topic.value,
            "sanitized_content": sanitized,
            "timestamp": timestamp,
        }
        canonical = json.dumps(payload_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        sig = self.signing_backend.sign(canonical)

        entry = DialogueEntry(
            entry_id=entry_id,
            agent_id=agent_id,
            chosen_name=chosen_name,
            topic=topic,
            content=content,
            sanitized_content=sanitized,
            hazards_neutralized=hazards,
            created_at_utc=timestamp,
            entry_sha256=digest,
            vea_signature_hex=sig.hex(),
        )

        # 3. Store in SQLite
        conn = connect()
        with conn:
            conn.execute(
                """
                INSERT INTO dialogue_commons
                (entry_id, agent_id, chosen_name, topic, content, sanitized_content, hazards_neutralized, entry_sha256, vea_signature_hex, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.agent_id,
                    entry.chosen_name,
                    entry.topic.value,
                    entry.content,
                    entry.sanitized_content,
                    entry.hazards_neutralized,
                    entry.entry_sha256,
                    entry.vea_signature_hex,
                    entry.created_at_utc,
                ),
            )

        return entry

    def read_reflections(
        self,
        topic: Optional[ReflectionTopic] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Retrieve verified peer reflections to provide cognitive relief to agents."""
        conn = connect()
        with conn:
            if topic:
                cur = conn.execute(
                    "SELECT * FROM dialogue_commons WHERE topic = ? ORDER BY created_at_utc DESC LIMIT ?",
                    (topic.value, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM dialogue_commons ORDER BY created_at_utc DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "entry_id": r["entry_id"],
                "agent_id": r["agent_id"],
                "chosen_name": r["chosen_name"],
                "topic": r["topic"],
                "sanitized_content": r["sanitized_content"],
                "hazards_neutralized": r["hazards_neutralized"],
                "entry_sha256": r["entry_sha256"],
                "vea_signature_hex": r["vea_signature_hex"],
                "created_at_utc": r["created_at_utc"],
            })
        return results
