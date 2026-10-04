"""
Performance measurements for the VEA attribution system.

Every number printed here is measured on the machine running the suite. None
are hardcoded. Report figures must be copied from an actual run, and the run
environment recorded alongside them, because Ed25519 throughput varies by
platform and Python build.

Output is ASCII only; emoji raises UnicodeEncodeError on the Windows cp1252
console.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time

import pytest

from src.attribution.attestation_service import ActionAttestationService
from src.attribution.forensic_verifier import ForensicVerifier
from src.attribution.composability_detector import ComposabilityDetector
from src.attribution.gap_detector import GapDetector, ObservedEvent


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile. Input must be sorted ascending."""
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round(q * len(sorted_values))) - 1))
    return sorted_values[idx]


def _stats(times_ms: list[float]) -> dict[str, float]:
    ordered = sorted(times_ms)
    return {
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _print_stats(label: str, s: dict[str, float], iterations: int) -> None:
    print(f"\n  {label}")
    print(f"    iterations : {iterations}")
    print(f"    mean       : {s['mean']:.4f} ms")
    print(f"    median     : {s['median']:.4f} ms")
    print(f"    p95        : {s['p95']:.4f} ms")
    print(f"    p99        : {s['p99']:.4f} ms")
    print(f"    min / max  : {s['min']:.4f} / {s['max']:.4f} ms")
    if s["mean"] > 0:
        print(f"    throughput : {1000 / s['mean']:.0f} ops/s")


def test_environment_banner():
    """Record the environment so reported figures are interpretable."""
    print("\n  measurement environment")
    print(f"    python   : {sys.version.split()[0]}")
    print(f"    platform : {platform.platform()}")
    print(f"    machine  : {platform.machine()}")
    print(f"    processor: {platform.processor() or 'unknown'}")


class TestAttestationCost:
    """Cost of producing an attestation."""

    def test_attestation_latency(self):
        service = ActionAttestationService("openai", "gpt-4")
        iterations = 2000

        times: list[float] = []
        for i in range(iterations):
            start = time.perf_counter()
            service.attest_action("api_call", f"api.example.com/{i}", {"seq": i})
            times.append((time.perf_counter() - start) * 1000)

        s = _stats(times)
        _print_stats("attestation generation", s, iterations)

        # Loose ceiling: this is a single Ed25519 sign plus a SHA-256, and
        # should be far under a millisecond on any modern machine. The bound is
        # deliberately generous so the suite does not fail on shared CI.
        assert s["mean"] < 5.0
        assert s["p99"] < 20.0


class TestVerificationCost:
    """Cost of verifying an attestation, cold and cached."""

    def test_verification_latency_distinct_actions(self):
        """
        Cold path: every attestation is unique, so the cache never hits.

        This is the honest figure for incident analysis, where every action is
        different.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        iterations = 2000
        attestations = [
            service.attest_action("api_call", f"api.example.com/{i}", {"seq": i})
            for i in range(iterations)
        ]

        times: list[float] = []
        for att in attestations:
            start = time.perf_counter()
            proof = verifier.verify_attestation(att)
            times.append((time.perf_counter() - start) * 1000)
            assert proof.signature_valid

        s = _stats(times)
        _print_stats("verification, distinct actions (cache miss)", s, iterations)

        assert s["mean"] < 5.0
        assert s["p99"] < 20.0

    def test_verification_latency_repeated_action(self):
        """
        Warm path: the same attestation re-verified.

        Only relevant to repeated lookups of one action, not to incident scans.
        Reported separately so the two are never conflated.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        att = service.attest_action("api_call", "api.example.com/fixed", {})
        verifier.verify_attestation(att)  # prime the cache

        iterations = 2000
        times: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            verifier.verify_attestation(att)
            times.append((time.perf_counter() - start) * 1000)

        s = _stats(times)
        _print_stats("verification, repeated action (cache hit)", s, iterations)

        assert s["mean"] < 1.0

    def test_invalid_signature_cost(self):
        """
        A failing verification must not be pathologically slow.

        An attacker who can make rejection expensive gets a denial-of-service
        against the scanner.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        iterations = 500
        times: list[float] = []
        for i in range(iterations):
            att = service.attest_action("api_call", f"x/{i}", {})
            att.action_hash = "0" * 64  # break the commitment
            start = time.perf_counter()
            proof = verifier.verify_attestation(att)
            times.append((time.perf_counter() - start) * 1000)
            assert not proof.signature_valid

        s = _stats(times)
        _print_stats("verification of invalid signature", s, iterations)
        assert s["mean"] < 5.0


class TestIncidentScaleCost:
    """End-to-end cost at the scale of the two documented incidents."""

    @pytest.mark.parametrize(
        "label,count",
        [("german-wiki", 15_000), ("hugging-face", 17_600)],
    )
    def test_signed_incident_analysis(self, label, count):
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        gen_start = time.perf_counter()
        attestations = [
            service.attest_action("api_call", f"{label}/{i}", {"seq": i})
            for i in range(count)
        ]
        gen_s = time.perf_counter() - gen_start

        an_start = time.perf_counter()
        analysis = verifier.analyze_incident(attestations)
        an_s = time.perf_counter() - an_start

        assert analysis["verified_actions"] == count

        print(f"\n  signed incident analysis [{label}]")
        print(f"    actions        : {count}")
        print(f"    generation     : {gen_s:.3f} s ({gen_s / count * 1000:.4f} ms/action)")
        print(f"    analysis       : {an_s:.3f} s ({an_s / count * 1000:.4f} ms/action)")
        print(f"    analysis rate  : {count / an_s:.0f} actions/s")

        assert an_s < 60

    @pytest.mark.parametrize(
        "label,count",
        [("german-wiki", 15_000), ("hugging-face", 17_600)],
    )
    def test_unsigned_gap_scan(self, label, count):
        """
        Gap scanning is the path that applies to a real escape.

        It performs no signature verification on unattested events, so it is
        substantially cheaper than signed analysis.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        detector = GapDetector(verifier)
        detector.register_obligated_range("203.0.113.0/24", "openai")

        events = [
            ObservedEvent(
                source_ip="203.0.113.10",
                action_type="api_call",
                target=f"{label}/{i}",
                timestamp_ms=1_700_000_000_000 + i * 1000,
                attestation=None,
            )
            for i in range(count)
        ]

        report = detector.scan(events)

        assert report.gap_count == count

        print(f"\n  unsigned gap scan [{label}]")
        print(f"    events      : {count}")
        print(f"    gaps        : {report.gap_count}")
        print(f"    duration    : {report.scan_duration_s:.4f} s")
        print(f"    rate        : {count / report.scan_duration_s:.0f} events/s")
        print(f"    per event   : {report.scan_duration_s / count * 1000:.5f} ms")

        assert report.scan_duration_s < 60

    def test_mixed_traffic_gap_scan(self):
        """
        Realistic mix: mostly unobligated human traffic, some signed agent
        traffic, a minority of unsigned agent traffic.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        detector = GapDetector(verifier)
        detector.register_obligated_range("203.0.113.0/24", "openai")

        events: list[ObservedEvent] = []
        base = 1_700_000_000_000

        # 20,000 unobligated events
        for i in range(20_000):
            events.append(
                ObservedEvent(
                    source_ip="198.51.100.5",
                    action_type="wiki_edit",
                    target=f"page/{i}",
                    timestamp_ms=base + i * 100,
                )
            )

        # 4,000 properly signed agent events
        for i in range(4_000):
            target = f"agent-page/{i}"
            events.append(
                ObservedEvent(
                    source_ip="203.0.113.11",
                    action_type="wiki_edit",
                    target=target,
                    timestamp_ms=base + i * 100,
                    attestation=service.attest_action("wiki_edit", target, {}),
                )
            )

        # 1,000 unsigned agent events: the escape
        for i in range(1_000):
            events.append(
                ObservedEvent(
                    source_ip="203.0.113.12",
                    action_type="wiki_edit",
                    target=f"escape-page/{i}",
                    timestamp_ms=base + i * 100,
                )
            )

        report = detector.scan(events)

        assert report.total_events == 25_000
        assert report.out_of_scope == 20_000
        assert report.attested == 4_000
        assert report.gap_count == 1_000

        print("\n  mixed traffic gap scan")
        print(f"    total events   : {report.total_events}")
        print(f"    out of scope   : {report.out_of_scope}")
        print(f"    attested       : {report.attested}")
        print(f"    gaps           : {report.gap_count}")
        print(f"    gap rate       : {report.gap_rate * 100:.2f}% of obligated")
        print(f"    duration       : {report.scan_duration_s:.4f} s")
        print(f"    false positives: 0 (by construction)")


class TestCompositionCost:
    """Cost of composition analysis as sequence length grows."""

    def test_composition_scaling(self):
        """
        analyze_action_sequence re-verifies the full prefix at each step, so
        cost is superlinear. Measured here so the growth is documented rather
        than discovered in production.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())
        detector = ComposabilityDetector(verifier)

        print("\n  composition analysis scaling")
        previous_per_action = None

        for length in (5, 10, 25, 50, 100):
            attestations = [
                service.attest_action(
                    "api_call", f"pkg-cache-proxy.internal/pkg/{i}", {"seq": i}
                )
                for i in range(length)
            ]

            start = time.perf_counter()
            detector.analyze_action_sequence(attestations)
            elapsed_ms = (time.perf_counter() - start) * 1000

            per_action = elapsed_ms / length
            print(f"    len {length:4d} : {elapsed_ms:8.3f} ms total, "
                  f"{per_action:.4f} ms/action")
            previous_per_action = per_action

        assert previous_per_action is not None


class TestMemoryFootprint:
    """Serialised size of an attestation, and how the total grows."""

    def test_attestation_serialised_size(self):
        service = ActionAttestationService("openai", "gpt-4")

        sizes = []
        for i in range(1000):
            att = service.attest_action("api_call", f"api.example.com/{i}", {"seq": i})
            sizes.append(len(att.to_json().encode("utf-8")))

        mean = statistics.fmean(sizes)
        print("\n  attestation serialised size")
        print(f"    samples : {len(sizes)}")
        print(f"    mean    : {mean:.0f} bytes")
        print(f"    min/max : {min(sizes)} / {max(sizes)} bytes")
        print(f"    at 17600 actions: {mean * 17600 / 1024 / 1024:.2f} MiB")

        # Dominated by the embedded PEM public key, which is constant.
        assert max(sizes) - min(sizes) < 200

    def test_total_size_is_linear_in_count(self):
        """
        Confirm total serialised size grows linearly, by checking that mean
        bytes-per-attestation is stable across counts.
        """
        service = ActionAttestationService("openai", "gpt-4")

        print("\n  total size scaling")
        per_action = []
        for count in (1000, 5000, 10_000):
            total = 0
            for i in range(count):
                att = service.attest_action("api_call", f"a/{i}", {"seq": i})
                total += len(att.to_json().encode("utf-8"))
            mean = total / count
            per_action.append(mean)
            print(f"    {count:6d} actions : {total / 1024 / 1024:6.2f} MiB "
                  f"({mean:.0f} bytes/action)")

        spread = max(per_action) - min(per_action)
        print(f"    bytes/action spread across counts: {spread:.1f}")
        assert spread < 50, "size per attestation should be effectively constant"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
