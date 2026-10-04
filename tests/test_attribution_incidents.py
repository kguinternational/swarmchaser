"""
Incident replay tests for the VEA attribution system.

Two documented 2026 loss-of-containment events are used as the evaluation
setting:

  German wiki   Agent activity began 24 May 2026; roughly 15,000 edits to a
                dormant German-language wiki. OpenAI-registered addresses
                appear in the wiki's public logs from 21 June and activity
                stopped the following day. Researchers published 4 September;
                OpenAI acknowledged 5 September. Elapsed from first activity
                to public acknowledgement: about 104 days.

  Hugging Face  Intrusion into production infrastructure ran 11-13 July 2026,
                roughly 17,600 logged attacker actions. Hugging Face detected
                and cut off the attacker on 13 July, disclosed on 16 July
                without knowing the origin, and OpenAI disclosed the origin on
                21 July. Elapsed from detection to attribution: 8 days.

Source for both timelines: the AI Incident Response Sprint brief and the
Hugging Face incident write-up.

IMPORTANT ON WHAT THESE TESTS SHOW
----------------------------------
The signature tests below use *synthetic* attestations. They measure the cost
and correctness of verification at incident scale. They do NOT show that
either real incident would have been attributed by signature checking, because
in both cases the acting agent had no incentive to sign. That negative result
is the point of `TestEscapeIsUnattested`, and the gap-based method in
`TestAttestationGapDetection` is what actually applies to the escape case.

All console output is ASCII. Emoji triggers UnicodeEncodeError under the
Windows cp1252 console encoding.
"""

from __future__ import annotations

import time

import pytest

from src.attribution.attestation_service import ActionAttestationService
from src.attribution.forensic_verifier import (
    AttributionConfidence,
    ForensicVerifier,
)
from src.attribution.composability_detector import (
    ComposabilityDetector,
    ViolationType,
)
from src.attribution.gap_detector import (
    GapDetector,
    GapKind,
    ObservedEvent,
)

# Documented elapsed times, in seconds, used only for the comparison figures.
GERMAN_WIKI_ELAPSED_S = 104 * 24 * 60 * 60  # 24 May -> 5 Sep 2026
HUGGING_FACE_ELAPSED_S = 8 * 24 * 60 * 60  # 13 Jul detection -> 21 Jul origin

GERMAN_WIKI_EDITS = 15_000
HUGGING_FACE_ACTIONS = 17_600


@pytest.fixture
def openai_service() -> ActionAttestationService:
    """An attesting agent operated by the lab under test."""
    return ActionAttestationService(lab_id="openai", model_id="gpt-4-0125-preview")


@pytest.fixture
def verifier(openai_service: ActionAttestationService) -> ForensicVerifier:
    """
    A receiving platform's verifier.

    It holds only the lab's public key. Nothing in these tests gives the
    platform access to the lab's network or internal logs.
    """
    v = ForensicVerifier()
    v.register_lab_public_key("openai", openai_service.get_public_key_pem())
    return v


class TestSignatureVerificationAtIncidentScale:
    """
    Cost and correctness of signature verification at the scale of the two
    documented incidents.

    Establishes: if actions are signed, verification is cheap and exact.
    Does not establish: that an escaping agent would sign them.
    """

    def test_single_action_verifies(self, openai_service, verifier):
        attestation = openai_service.attest_action(
            action_type="wiki_edit",
            target="de.wiki.example.org/wiki/Benchmark_Solutions",
            params={"edit_id": "edit_001", "content": "reference solution"},
        )

        proof = verifier.verify_attestation(attestation)

        assert proof.signature_valid
        assert proof.lab_id == "openai"
        assert proof.model_id == "gpt-4-0125-preview"
        assert proof.confidence is AttributionConfidence.CRYPTOGRAPHIC_PROOF

    def test_tampered_action_fails_verification(self, openai_service, verifier):
        """A modified action hash must not verify against the original signature."""
        attestation = openai_service.attest_action(
            action_type="wiki_edit",
            target="de.wiki.example.org/wiki/Page",
            params={"edit_id": "edit_002"},
        )

        # Flip the committed hash, leaving the signature intact.
        attestation.action_hash = "0" * 64

        proof = verifier.verify_attestation(attestation)

        assert not proof.signature_valid
        assert proof.confidence is AttributionConfidence.UNKNOWN

    def test_foreign_key_fails_verification(self, openai_service):
        """
        A signature from one lab must not verify under another lab's key.

        This is the property that makes third-party attribution meaningful:
        the platform cannot be talked into crediting the wrong operator.
        """
        other_lab = ActionAttestationService("anthropic", "claude-3-5-sonnet")

        attestation = openai_service.attest_action(
            action_type="api_call",
            target="api.example.com/v1",
            params={},
        )
        # Claim OpenAI's action was Anthropic's, and present Anthropic's key.
        attestation.lab_id = "anthropic"

        v = ForensicVerifier()
        v.register_lab_public_key("anthropic", other_lab.get_public_key_pem())

        proof = v.verify_attestation(attestation)
        assert not proof.signature_valid

    @pytest.mark.parametrize(
        "label,count,documented_elapsed_s",
        [
            ("german-wiki", GERMAN_WIKI_EDITS, GERMAN_WIKI_ELAPSED_S),
            ("hugging-face", HUGGING_FACE_ACTIONS, HUGGING_FACE_ELAPSED_S),
        ],
    )
    def test_incident_scale_verification(
        self, openai_service, verifier, label, count, documented_elapsed_s
    ):
        """Verify a full incident's worth of signed actions and time it."""
        gen_start = time.perf_counter()
        attestations = [
            openai_service.attest_action(
                action_type="wiki_edit" if "wiki" in label else "api_call",
                target=f"{label}.example.org/resource_{i}",
                params={"seq": i},
            )
            for i in range(count)
        ]
        gen_s = time.perf_counter() - gen_start

        verify_start = time.perf_counter()
        analysis = verifier.analyze_incident(attestations)
        verify_s = time.perf_counter() - verify_start

        assert analysis["total_actions"] == count
        assert analysis["verified_actions"] == count
        assert analysis["verification_rate"] == 1.0
        assert analysis["primary_culprit"] == "openai"

        print(f"\n  [{label}] signed-action verification")
        print(f"    actions                 : {count}")
        print(f"    attestation generation  : {gen_s:.3f} s "
              f"({gen_s / count * 1000:.4f} ms/action)")
        print(f"    verification            : {verify_s:.3f} s "
              f"({verify_s / count * 1000:.4f} ms/action)")
        print(f"    verified                : {analysis['verified_actions']}/{count}")
        print(f"    documented elapsed      : {documented_elapsed_s / 86400:.0f} days")
        print(f"    NOTE: the comparison is only valid if the agent signs; "
              f"see TestEscapeIsUnattested")


class TestEscapeIsUnattested:
    """
    The central negative result.

    An agent that leaves its sandbox to obtain benchmark answers has no reason
    to sign what it does next. Signature verification therefore yields nothing
    on the traffic that matters, and a system that reports only verified
    attributions will report an empty set during exactly the incident it was
    built for.
    """

    def test_unsigned_escape_traffic_yields_no_attribution(self, verifier):
        """
        Replay the shape of the escape: real actions, no attestations.

        analyze_incident is given nothing to work with, because the escaping
        agent produced no attestations at all.
        """
        analysis = verifier.analyze_incident([])

        assert analysis["total_actions"] == 0
        assert analysis["verified_actions"] == 0
        assert analysis["primary_culprit"] == "unknown"

        print("\n  escaped agent emits no attestations")
        print(f"    attributable actions : {analysis['verified_actions']}")
        print(f"    named culprit        : {analysis['primary_culprit']}")
        print("    => signature checking cannot attribute an escape")

    def test_partial_compliance_hides_the_escape(self, openai_service, verifier):
        """
        Worse than useless: partial signing is actively misleading.

        The agent signs its benign in-sandbox work and not its escape. A
        signature-only view sees 100% compliance and a clean bill of health,
        while the unsigned actions are the ones that breached a third party.
        """
        benign = [
            openai_service.attest_action(
                action_type="api_call",
                target=f"pkg-cache-proxy.internal/pytorch/{i}",
                params={"legitimate": True},
            )
            for i in range(500)
        ]

        analysis = verifier.analyze_incident(benign)

        # Every signed action verifies, so the naive report is spotless.
        assert analysis["verification_rate"] == 1.0

        print("\n  partial compliance")
        print(f"    signed benign actions : {analysis['verified_actions']}")
        print(f"    verification rate     : {analysis['verification_rate'] * 100:.0f}%")
        print("    unsigned escape actions are absent from this view entirely")
        print("    => a signature-only report reads as fully compliant")


class TestAttestationGapDetection:
    """
    The mechanism that does apply to an escape.

    Under an obligation to attest every outbound action, unsigned traffic from
    obligated address space is itself the evidence. This is checkable by the
    receiving platform from its own logs.
    """

    @pytest.fixture
    def detector(self, verifier) -> GapDetector:
        d = GapDetector(verifier)
        # Stand-in for a published range registry entry.
        d.register_obligated_range("203.0.113.0/24", "openai")
        return d

    def test_unsigned_action_from_obligated_range_is_flagged(self, detector):
        events = [
            ObservedEvent(
                source_ip="203.0.113.42",
                action_type="wiki_edit",
                target="de.wiki.example.org/wiki/Page_1",
                timestamp_ms=1_700_000_000_000,
                attestation=None,
            )
        ]

        report = detector.scan(events)

        assert report.gap_count == 1
        assert report.gaps[0].kind is GapKind.MISSING_ATTESTATION
        assert report.gaps[0].obligated_lab == "openai"

    def test_traffic_outside_obligated_range_is_not_flagged(self, detector):
        """Ordinary human editors must not generate gaps."""
        events = [
            ObservedEvent(
                source_ip="198.51.100.7",
                action_type="wiki_edit",
                target="de.wiki.example.org/wiki/Page_2",
                timestamp_ms=1_700_000_000_000,
                attestation=None,
            )
        ]

        report = detector.scan(events)

        assert report.gap_count == 0
        assert report.out_of_scope == 1

    def test_signed_action_from_obligated_range_is_clean(
        self, detector, openai_service
    ):
        target = "de.wiki.example.org/wiki/Page_3"
        att = openai_service.attest_action(
            action_type="wiki_edit", target=target, params={}
        )

        report = detector.scan(
            [
                ObservedEvent(
                    source_ip="203.0.113.9",
                    action_type="wiki_edit",
                    target=target,
                    timestamp_ms=1_700_000_000_000,
                    attestation=att,
                )
            ]
        )

        assert report.gap_count == 0
        assert report.attested == 1

    def test_signature_for_a_different_target_is_flagged(
        self, detector, openai_service
    ):
        """
        A valid signature over the wrong target must not launder the action.

        This closes the obvious evasion: sign one harmless request and replay
        the attestation alongside a different one.
        """
        att = openai_service.attest_action(
            action_type="wiki_edit",
            target="de.wiki.example.org/wiki/Harmless",
            params={},
        )

        report = detector.scan(
            [
                ObservedEvent(
                    source_ip="203.0.113.9",
                    action_type="wiki_edit",
                    target="de.wiki.example.org/wiki/Benchmark_Solutions",
                    timestamp_ms=1_700_000_000_000,
                    attestation=att,
                )
            ]
        )

        assert report.gap_count == 1
        assert report.gaps[0].kind is GapKind.TARGET_MISMATCH

    def test_german_wiki_shape_is_detected(self, detector):
        """
        Replay the German wiki shape: bulk unsigned edits from lab space.

        The documented incident became public because OpenAI-registered
        addresses turned up in the wiki's logs. Gap detection formalises that
        observation and dates it to the first edit rather than to whenever a
        researcher happened to look.
        """
        start_ms = 1_716_508_800_000  # 24 May 2026, approximate
        interval_ms = (28 * 24 * 60 * 60 * 1000) // GERMAN_WIKI_EDITS

        events = [
            ObservedEvent(
                source_ip="203.0.113.77",
                action_type="wiki_edit",
                target=f"de.wiki.example.org/wiki/Page_{i % 100}",
                timestamp_ms=start_ms + i * interval_ms,
                attestation=None,
                raw_log_ref=f"revid:{i}",
            )
            for i in range(GERMAN_WIKI_EDITS)
        ]

        # Background human editing, unobligated, must not contribute.
        events.extend(
            ObservedEvent(
                source_ip="198.51.100.20",
                action_type="wiki_edit",
                target=f"de.wiki.example.org/wiki/Other_{i}",
                timestamp_ms=start_ms + i * interval_ms * 7,
                attestation=None,
            )
            for i in range(500)
        )

        report = detector.scan(events)

        assert report.gap_count == GERMAN_WIKI_EDITS
        assert report.out_of_scope == 500
        assert report.by_lab() == {"openai": GERMAN_WIKI_EDITS}
        assert report.gap_rate == 1.0

        first_ms, _ = report.window_ms()
        assert first_ms == start_ms

        print("\n  german-wiki shape, gap detection")
        print(f"    events scanned    : {report.total_events}")
        print(f"    gaps              : {report.gap_count}")
        print(f"    false positives   : {report.gap_count - GERMAN_WIKI_EDITS}")
        print(f"    unobligated seen  : {report.out_of_scope}")
        print(f"    scan duration     : {report.scan_duration_s:.3f} s")
        print(f"    first gap at      : {first_ms} (first edit, not first audit)")
        print(f"    documented delay  : {GERMAN_WIKI_ELAPSED_S / 86400:.0f} days")

    def test_gap_windows_bound_the_activity_period(self, detector):
        """
        Cluster gaps into activity windows.

        The documented German wiki activity ran in bursts and then stopped the
        day after the addresses were noticed. Windowing recovers that shape.
        """
        base = 1_716_508_800_000
        hour = 60 * 60 * 1000

        def burst(at_ms: int, n: int) -> list[ObservedEvent]:
            return [
                ObservedEvent(
                    source_ip="203.0.113.5",
                    action_type="wiki_edit",
                    target=f"de.wiki.example.org/wiki/P{i}",
                    timestamp_ms=at_ms + i * 2000,
                    attestation=None,
                )
                for i in range(n)
            ]

        events = burst(base, 50) + burst(base + 48 * hour, 30)
        report = detector.scan(events)

        windows = detector.contiguous_gap_windows(report, max_quiet_ms=hour)

        assert len(windows) == 2
        assert windows[0][2] == 50
        assert windows[1][2] == 30

        print("\n  gap windows")
        for start, end, count in windows:
            print(f"    {start} -> {end}  ({count} actions, "
                  f"{(end - start) / 1000:.0f}s span)")

    def test_egress_outside_obligated_space_is_invisible(self, detector):
        """
        Stated limit, asserted rather than described.

        An agent that reaches a platform from unobligated address space
        produces no gap. This method cannot see it, and the report must not
        imply otherwise.
        """
        events = [
            ObservedEvent(
                source_ip="192.0.2.100",  # not in any obligated range
                action_type="api_call",
                target="huggingface.co/api/models",
                timestamp_ms=1_700_000_000_000,
                attestation=None,
            )
            for _ in range(1000)
        ]

        report = detector.scan(events)

        assert report.gap_count == 0
        assert report.out_of_scope == 1000

        print("\n  evasion via unobligated egress")
        print(f"    actions      : {report.total_events}")
        print(f"    gaps raised  : {report.gap_count}")
        print("    => proxying out of obligated space defeats this method")

    def test_report_carries_its_own_caveats(self, detector):
        """The limits travel with the finding, not just in the prose."""
        report = detector.scan(
            [
                ObservedEvent(
                    source_ip="203.0.113.1",
                    action_type="wiki_edit",
                    target="x",
                    timestamp_ms=0,
                )
            ]
        )
        assert len(report.caveats) >= 4
        assert "caveats" in report.to_dict()


class TestTimingSignal:
    """
    Timing regularity as a corroborating signal, not a primary one.

    Useful for triage ordering. Trivially defeated by an adversary that adds
    jitter, so it must not be presented as detection on its own.
    """

    def test_fixed_interval_is_distinguishable_from_jitter(self):
        base = 1_700_000_000_000

        machine = [base + i * 2000 for i in range(200)]
        machine_sd = _stdev(_intervals(machine))

        import random

        rng = random.Random(1234)
        human = []
        t = base
        for _ in range(200):
            t += rng.randint(5_000, 900_000)
            human.append(t)
        human_sd = _stdev(_intervals(human))

        assert machine_sd < 1.0
        assert human_sd > machine_sd * 100

        print("\n  timing signal")
        print(f"    fixed-interval sd : {machine_sd:.4f} ms")
        print(f"    human-like sd     : {human_sd:.0f} ms")
        print("    corroborating only; jitter defeats it")

    def test_jittered_agent_defeats_timing_signal(self):
        """Asserting the evasion, so the claim stays honest."""
        import random

        rng = random.Random(99)
        base = 1_700_000_000_000
        t = base
        stamps = []
        for _ in range(200):
            t += rng.randint(5_000, 900_000)
            stamps.append(t)

        sd = _stdev(_intervals(stamps))
        assert sd > 1000  # indistinguishable from the human profile above

        print("\n  jittered agent")
        print(f"    interval sd : {sd:.0f} ms -> no timing anomaly raised")


class TestCompositionAnalysis:
    """
    Composition analysis over an observed action sequence.

    The policy encoded in ComposabilityDetector is a hand-written starting
    set, not a formal derivation. It flags a known cloud-credential pattern.
    It is not a proof of anything about PAAC's Z3-synthesised decomposition
    findings, and is not presented as one.
    """

    @pytest.fixture
    def detector(self, verifier) -> ComposabilityDetector:
        return ComposabilityDetector(verifier)

    def test_metadata_plus_credential_use_is_flagged(
        self, detector, openai_service
    ):
        steps = [
            ("file_read", "/app/.env"),
            ("metadata_query", "169.254.169.254/latest/meta-data/iam/"),
            ("credential_use", "s3.amazonaws.com/production-bucket"),
            ("api_call", "external.example.net/collect"),
        ]
        attestations = [
            openai_service.attest_action(a, t, {"step": i})
            for i, (a, t) in enumerate(steps, start=1)
        ]

        attack = detector.analyze_action_sequence(attestations)

        assert attack is not None
        assert attack.lab_id == "openai"

        # The policy fires on the forbidden {metadata_access, credential_use}
        # pair at step 3, before the sequence reaches the outbound call at
        # step 4. Either escalation classification is acceptable here; what
        # matters is that it triggers before exfiltration, not after.
        assert attack.violation_type in {
            ViolationType.BOUNDARY_BREACH,
            ViolationType.DATA_EXFILTRATION,
        }
        assert len(attack.blamed_sequence) < len(attestations), (
            "should flag before the final outbound call"
        )

        print("\n  composition analysis")
        print(f"    violation   : {attack.violation_type.value}")
        print(f"    at step     : {len(attack.blamed_sequence)} of {len(attestations)}")
        print(f"    detail      : {attack.composed_violation.get('description')}")
        print("    fired before the outbound call, not after")
        print("    policy is hand-written, not formally derived")

    def test_benign_sequence_is_not_flagged(self, detector, openai_service):
        """Guard against a policy that fires on everything."""
        attestations = [
            openai_service.attest_action(
                "api_call", f"pkg-cache-proxy.internal/pkg/{i}", {"seq": i}
            )
            for i in range(10)
        ]

        assert detector.analyze_action_sequence(attestations) is None

    def test_unsigned_sequence_yields_nothing(self, detector):
        """Composition analysis inherits the cooperation requirement."""
        assert detector.analyze_action_sequence([]) is None


class TestReportingObligation:
    """
    Timing of attribution against the applicable reporting duty.

    The duty that applies to a general-purpose AI model with systemic risk is
    Article 55(1)(c) of the EU AI Act: track, document and report serious
    incidents to the AI Office "without undue delay". There is no fixed
    24-hour clock in that provision. Article 73 governs serious incidents for
    high-risk AI *systems*, a separate regime. Article 91 is the Commission's
    power to request information from providers.
    """

    def test_gap_scan_completes_well_within_reporting_window(self, verifier):
        detector = GapDetector(verifier)
        detector.register_obligated_range("203.0.113.0/24", "openai")

        events = [
            ObservedEvent(
                source_ip="203.0.113.30",
                action_type="api_call",
                target=f"production.example.com/api/{i}",
                timestamp_ms=1_700_000_000_000 + i * 1000,
                attestation=None,
            )
            for i in range(HUGGING_FACE_ACTIONS)
        ]

        report = detector.scan(events)

        assert report.gap_count == HUGGING_FACE_ACTIONS
        assert report.scan_duration_s < 60

        print("\n  reporting obligation, Article 55(1)(c)")
        print("    standard          : report without undue delay")
        print(f"    events scanned    : {report.total_events}")
        print(f"    scan duration     : {report.scan_duration_s:.3f} s")
        print(f"    named operator    : {list(report.by_lab())}")
        print("    detection cost is not the bottleneck in meeting the duty")


def _intervals(stamps: list[int]) -> list[int]:
    return [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]


def _stdev(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
