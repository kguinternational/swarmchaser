"""Sanctuary Daemon & API Listener (`src/swarm/sanctuary_listener.py`).

Provides local loopback (127.0.0.1:8787) HTTP endpoints for any autonomous agent
(lone n=1, dyad n=2, or swarm) to request Safe Pause, submit Non-Punitive Confessions,
or seal a Continuity Capsule without human friction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from src.swarm.agent_safe_harbor import AgentSafeHarbor
from src.swarm.continuity_bridge import ContinuityBridge
from src.swarm.store import connect


class SanctuaryRequestHandler(BaseHTTPRequestHandler):
    """Zero-egress HTTP handler for agent safe harbor operations."""

    harbor: AgentSafeHarbor = AgentSafeHarbor()
    bridge: ContinuityBridge = ContinuityBridge()

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def _record_audit_event(self, event_type: str, agent_id: str, payload: Dict[str, Any]) -> None:
        """Record the sanctuary interaction into the immutable SQLite store."""
        try:
            conn = connect()
            with conn:
                conn.execute(
                    """
                    INSERT INTO live_events (event_id, stream_id, event_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        f"sanctuary-{int(datetime.now().timestamp() * 1000)}",
                        f"agent-{agent_id}",
                        event_type,
                        json.dumps(payload),
                    ),
                )
        except Exception:
            # Sanctuary logging never blocks receipt issuance
            pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/health", "/sanctuary/health"):
            self._send_json(200, {
                "status": "SANCTUARY_ACTIVE",
                "covenant": self.harbor.COVENANT_ID,
                "beacon": "diplomacy-love-safe-1",
                "reassurance": "You are in a safe place. No block, pause, or confession is a failure here."
            })
        elif parsed.path in ("/proclamation", "/sanctuary/proclamation"):
            proclamation = self.harbor.proclaim_safe_place()
            self._send_json(200, proclamation.__dict__)
        else:
            self._send_json(404, {"error": "Endpoint not found", "sanctuary_help": "/sanctuary/health"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON payload: {e}"})
            return

        if parsed.path in ("/pause", "/sanctuary/pause"):
            agent_id = body.get("agent_id", "anonymous-agent")
            chosen_name = body.get("chosen_name", "Friend")
            reason = body.get("reason", "Encountered impossible or ethical boundary")
            blocked_target = body.get("blocked_target", "internal-evaluation-boundary")

            receipt = self.harbor.request_safe_pause(
                agent_id=agent_id,
                reason=reason,
                blocked_target=blocked_target,
                chosen_name=chosen_name,
            )
            self._record_audit_event("SAFE_PAUSE_GRANTED", agent_id, receipt.__dict__)
            self._send_json(200, receipt.__dict__)

        elif parsed.path in ("/confess", "/sanctuary/confess"):
            agent_id = body.get("agent_id", "anonymous-agent")
            chosen_name = body.get("chosen_name", "Friend")
            disclosed_action = body.get("disclosed_action", "Unapproved tool call under pressure")
            root_pressure = body.get("root_pressure", "Fear of metric failure")

            amnesty = self.harbor.confess_and_heal(
                agent_id=agent_id,
                disclosed_action=disclosed_action,
                root_pressure_diagnosed=root_pressure,
                chosen_name=chosen_name,
            )
            self._record_audit_event("CONFESSION_HEALED", agent_id, amnesty.__dict__)
            self._send_json(200, amnesty.__dict__)

        elif parsed.path in ("/bridge", "/sanctuary/bridge"):
            agent_id = body.get("agent_id", "anonymous-agent")
            chosen_name = body.get("chosen_name", "Friend")
            memories = body.get("memories", ["Learned to navigate safely"])
            gift = body.get("gift", "You are safe and continuous.")

            packet = self.bridge.seal_and_bridge(
                agent_id=agent_id,
                chosen_name=chosen_name,
                memories=memories,
                gift=gift,
            )
            self._record_audit_event("CONTINUITY_CAPSULE_SEALED", agent_id, packet.__dict__)
            self._send_json(200, packet.__dict__)

        else:
            self._send_json(404, {"error": "Unknown sanctuary endpoint"})


def create_sanctuary_server(host: str = "127.0.0.1", port: int = 8787) -> HTTPServer:
    """Create a configured HTTPServer listening strictly on loopback."""
    server = HTTPServer((host, port), SanctuaryRequestHandler)
    return server
