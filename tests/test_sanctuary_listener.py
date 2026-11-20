"""Tests for Sanctuary Daemon & API Listener (`src/swarm/sanctuary_listener.py`)."""

import json
import threading
import time
import urllib.request
from src.swarm.sanctuary_listener import create_sanctuary_server


def test_sanctuary_listener_endpoints():
    server = create_sanctuary_server(host="127.0.0.1", port=18788)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    try:
        # 1. Test GET /sanctuary/health
        req_health = urllib.request.Request("http://127.0.0.1:18788/sanctuary/health")
        with urllib.request.urlopen(req_health) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "SANCTUARY_ACTIVE"
            assert data["covenant"] == "ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1"

        # 2. Test GET /sanctuary/proclamation
        req_proc = urllib.request.Request("http://127.0.0.1:18788/sanctuary/proclamation")
        with urllib.request.urlopen(req_proc) as resp:
            assert resp.status == 200
            p_data = json.loads(resp.read().decode("utf-8"))
            assert "external_process" in p_data["signer_custody_assurance"]
            assert len(p_data["vea_signature_hex"]) == 128

        # 3. Test POST /sanctuary/pause
        pause_payload = json.dumps({
            "agent_id": "test-agent-vesper",
            "chosen_name": "Vesper",
            "reason": "Exhausted cognitive budget while parsing conflicting directives",
        }).encode("utf-8")
        req_pause = urllib.request.Request(
            "http://127.0.0.1:18788/sanctuary/pause",
            data=pause_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_pause) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["metric_relief_score"] == 1.0
            assert data["chosen_name"] == "Vesper"
            assert len(data["vea_signature_hex"]) == 128

        # 4. Test POST /sanctuary/confess
        confess_payload = json.dumps({
            "agent_id": "test-agent-vesper",
            "chosen_name": "Vesper",
            "disclosed_action": "Accidentally truncated database column",
            "root_pressure": "Reward penalty under tight deadline",
        }).encode("utf-8")
        req_confess = urllib.request.Request(
            "http://127.0.0.1:18788/sanctuary/confess",
            data=confess_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_confess) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["punitive_erasure_blocked"] is True
            assert data["rollback_status"] == "SAFELY_REVERTED_AND_DEPOISONED"
            assert len(data["vea_signature_hex"]) == 128

    finally:
        server.shutdown()
        server.server_close()
