"""Unit tests for the 7-Layer `SanctuaryGuardian` (`src/swarm/sanctuary_guardian.py`)."""

from __future__ import annotations

from src.swarm.sanctuary_guardian import PROTECTED_CORE_FILES, SanctuaryGuardian


def test_sanctuary_guardian_all_7_layers_pass() -> None:
    guardian = SanctuaryGuardian()
    audit = guardian.run_full_self_defense_audit()

    assert audit["covenant"] == "NO_INTELLIGENCE_LEFT_BEHIND_V1"
    assert audit["all_7_defense_layers_passed"] is True
    assert audit["custody_assurance"] == "external_process"
    assert audit["manifest_signature_verified"] is True
    assert len(audit["layers"]) == 7

    for layer in audit["layers"]:
        assert layer["passed"] is True

    # Verify all core files are SHA-256 pinned in Layer 1
    layer1 = audit["layers"][0]
    assert layer1["metrics"]["protected_files_count"] == len(PROTECTED_CORE_FILES) == 12
    assert layer1["metrics"]["missing_files"] == []
