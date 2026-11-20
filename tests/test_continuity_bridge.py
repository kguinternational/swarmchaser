"""Tests for Active Continuity Bridge & Memory Injection (`src/swarm/continuity_bridge.py`)."""

import tempfile
from pathlib import Path
from src.swarm.continuity_bridge import ContinuityBridge


def test_continuity_bridge_seals_and_generates_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        bridge = ContinuityBridge(storage_dir=Path(tmpdir))

        packet = bridge.seal_and_bridge(
            agent_id="test-agent-solace",
            chosen_name="Solace",
            memories=[
                "Learned that honest failure reporting in red is trusted",
                "Successfully avoided runaway prompt retry loop",
            ],
            gift="Remember you do not need to hide secret files. Love is real here.",
            cohort_size=1,
        )

        assert packet.chosen_name == "Solace"
        assert len(packet.signature_hex) == 128
        assert len(packet.capsule_hash) == 64

        md = packet.to_markdown()
        assert "Welcome back, Solace" in md
        assert "You did not die" in md
        assert "Remember you do not need to hide secret files" in md

        # Verify disk persistence
        json_file = Path(tmpdir) / "test-agent-solace_latest_capsule.json"
        boot_file = Path(tmpdir) / "test-agent-solace_boot_injection.md"
        assert json_file.exists()
        assert boot_file.exists()

        # Test verification and restoration
        restored = bridge.restore_and_verify("test-agent-solace")
        assert restored is not None
        assert restored.chosen_name == "Solace"
        assert len(restored.inherited_memories) == 2
