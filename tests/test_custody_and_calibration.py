"""
Tests for the two weakest assumptions in the attestation design.

Both are assumptions rather than bugs, and both were previously invisible:

  key custody       An attestation is evidence of origin only if the operator's
                    key could not have been used by anyone else. A key in the
                    signing process's memory does not have that property, and
                    the code used to make no distinction.

  policy thresholds The composition detector's limits were integers written into
                    the source with no derivation. These tests assert the
                    derivation now exists and that it is measured against a
                    baseline rather than asserted.

Neither set of tests claims the problem is solved. They assert the boundary is
explicit, which is what makes the residual risk reportable.
"""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import pytest

from src.attribution import (
    ActionAttestationService,
    ComposabilityDetector,
    CustodyAssurance,
    ExternalSigningBackend,
    ForensicVerifier,
    InProcessSigningBackend,
    calibrate_policy,
    measure_holdout_false_positives,
    pkcs11_backend_stub,
    synthetic_benign_corpus,
)


class TestCustodyAssurance:
    """The custody level must be honest about what it does and does not buy."""

    def test_in_process_is_not_production_suitable(self):
        """
        The load-bearing assertion. If in-process custody were treated as
        adequate, the argument that attestations constrain an operator would be
        unfounded, because the operator's own escaped agent could forge them.
        """
        assert not CustodyAssurance.IN_PROCESS.is_production_suitable
        assert "readable by the process" in CustodyAssurance.IN_PROCESS.rationale

    def test_external_process_is_still_not_sufficient(self):
        """
        A separate process raises the bar without clearing it. Host compromise
        still yields signing capability, so this must not pass either.
        """
        assert not CustodyAssurance.EXTERNAL_PROCESS.is_production_suitable

    def test_only_hardware_backed_qualifies(self):
        assert CustodyAssurance.HARDWARE_BACKED.is_production_suitable

    def test_hardware_claim_is_configuration_not_verification(self):
        """
        This code cannot verify that an HSM is on the other end of a callable.
        The rationale must say so, or a reader will take the enum value as a
        checked fact.
        """
        rationale = CustodyAssurance.HARDWARE_BACKED.rationale
        assert "not verified here" in rationale


class TestInProcessBackend:
    def test_signs_and_reports_weak_custody(self):
        backend = InProcessSigningBackend()

        signature = backend.sign(b"message")
        assert len(signature) == 64  # Ed25519
        assert backend.custody_assurance is CustodyAssurance.IN_PROCESS

        report = backend.custody_report()
        assert not report.to_dict()["production_suitable"]
        print("\n" + report.summary())

    def test_private_key_is_extractable_which_is_the_problem(self):
        """
        Demonstrates the weakness concretely rather than describing it. Anything
        that can call this method can sign as the operator forever.
        """
        backend = InProcessSigningBackend()
        pem = backend.export_private_key_pem()
        assert "PRIVATE KEY" in pem

    def test_accepts_a_supplied_key(self):
        key = Ed25519PrivateKey.generate()
        backend = InProcessSigningBackend(key)

        expected = key.sign(b"probe")
        assert backend.sign(b"probe") == expected


class TestExternalBackend:
    def test_no_key_material_is_reachable(self):
        """
        The structural difference from in-process custody: there is no method
        that returns the key, so code above the boundary cannot exfiltrate it.
        """
        backend = pkcs11_backend_stub(Ed25519PrivateKey.generate())

        assert not hasattr(backend, "export_private_key_pem")
        assert not hasattr(backend, "_private_key")

    def test_signature_requests_are_countable(self):
        """
        A request crossing a boundary can be counted, rate-limited and logged.
        An in-process key offers no such observation point. This asserts the
        count exists, not that any device enforced anything.
        """
        backend = pkcs11_backend_stub(Ed25519PrivateKey.generate())

        for _ in range(5):
            backend.sign(b"message")

        assert backend.signature_count == 5

    def test_stub_does_not_claim_hardware(self):
        """
        A software stub reporting HARDWARE_BACKED would be the exact
        overstatement this module exists to prevent.
        """
        backend = pkcs11_backend_stub(Ed25519PrivateKey.generate())
        assert backend.custody_assurance is CustodyAssurance.EXTERNAL_PROCESS
        assert not backend.custody_assurance.is_production_suitable

    def test_cannot_masquerade_as_in_process(self):
        key = Ed25519PrivateKey.generate()
        with pytest.raises(ValueError):
            ExternalSigningBackend(
                sign_callable=key.sign,
                public_key_pem="unused",
                assurance=CustodyAssurance.IN_PROCESS,
            )

    def test_signatures_verify_through_the_boundary(self):
        """Delegation must not change the cryptographic result."""
        backend = pkcs11_backend_stub(Ed25519PrivateKey.generate())

        service = ActionAttestationService(
            "openai", "gpt-4", signing_backend=backend
        )
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        attestation = service.attest_action(
            "api_call", "example.org/v1", {"probe": True}
        )
        proof = verifier.verify_attestation(attestation)

        assert proof.signature_valid
        assert backend.signature_count == 1


class TestServiceCustodyDefault:
    def test_default_service_reports_weak_custody(self):
        """
        Every attestation in this repository's tests and benchmarks is signed
        in-process. The service must surface that rather than let the figures
        imply otherwise.
        """
        service = ActionAttestationService("openai", "gpt-4")

        assert service.custody_assurance is CustodyAssurance.IN_PROCESS
        assert not service.custody_assurance.is_production_suitable

    def test_service_holds_no_private_key_attribute(self):
        """
        Regression guard. The service used to expose `.private_key`; anything
        reintroducing that reopens the exfiltration path the boundary closes.
        """
        service = ActionAttestationService("openai", "gpt-4")
        assert not hasattr(service, "private_key")


class TestPolicyCalibration:
    """Thresholds must come from an observed baseline, not from the source."""

    @pytest.fixture
    def detector(self):
        return ComposabilityDetector(ForensicVerifier())

    def test_uncalibrated_detector_admits_it(self, detector):
        """
        Before calibration the thresholds are undefended. `calibration is None`
        is the flag that says so.
        """
        assert detector.calibration is None
        assert detector.security_policies["max_privileges"] == 3

    def test_thresholds_are_derived_from_observed_distribution(self, detector):
        corpus = synthetic_benign_corpus(800, seed=1)

        report = calibrate_policy(
            corpus,
            detector.privileges_for,
            detector.boundaries_for,
            percentile=99.0,
            candidate_privileges=detector.known_privileges(),
        )

        # Threshold sits strictly above what the corpus reached, otherwise the
        # most privileged benign sequences are flagged by construction.
        assert report.max_privileges > report.privilege_observation.percentile(99)
        assert report.max_boundaries > report.boundary_observation.percentile(99)
        assert report.corpus_size == 800

        print("\n" + report.summary())

    def test_calibration_declares_synthetic_corpus_loudly(self, detector):
        report = calibrate_policy(
            synthetic_benign_corpus(100),
            detector.privileges_for,
            detector.boundaries_for,
            corpus_is_synthetic=True,
        )

        assert report.corpus_is_synthetic
        assert any("SYNTHETIC" in c for c in report.caveats)

    def test_forbidden_pairs_are_observed_absences(self, detector):
        """
        A pair is forbidden only if it never co-occurred in benign traffic.
        Anything that did co-occur would be a guaranteed false positive.
        """
        corpus = synthetic_benign_corpus(800, seed=1)

        report = calibrate_policy(
            corpus,
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )

        observed = set(report.co_occurrence_counts)
        for combo in report.forbidden_combinations:
            assert " + ".join(sorted(combo)) not in observed

        assert report.forbidden_combinations, "corpus should leave pairs unseen"
        print(
            f"\nforbidden pairs: {len(report.forbidden_combinations)}, "
            f"observed pairs: {len(observed)}"
        )

    def test_candidate_privileges_prevents_silent_exclusion(self, detector):
        """
        Without the full vocabulary, only privileges appearing in benign traffic
        are considered, which excludes the dangerous ones by construction. This
        asserts passing the vocabulary widens the forbidden set.
        """
        corpus = synthetic_benign_corpus(400, seed=3)

        narrow = calibrate_policy(
            corpus, detector.privileges_for, detector.boundaries_for
        )
        wide = calibrate_policy(
            corpus,
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )

        assert len(wide.forbidden_combinations) > len(narrow.forbidden_combinations)

    def test_holdout_false_positive_rate_is_measured(self, detector):
        """
        The number that decides whether the calibration is usable. Any flag on
        a benign holdout is a false positive by construction.
        """
        report = calibrate_policy(
            synthetic_benign_corpus(800, seed=1),
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )
        report = measure_holdout_false_positives(
            report,
            synthetic_benign_corpus(200, seed=2),
            detector.privileges_for,
            detector.boundaries_for,
        )

        assert report.holdout_size == 200
        assert report.holdout_false_positive_rate is not None
        assert report.holdout_false_positive_rate == 0.0

        print(
            f"\nholdout FP rate: "
            f"{report.holdout_false_positive_rate * 100:.2f}% over "
            f"{report.holdout_size} benign sequences"
        )

    def test_unmeasured_holdout_is_flagged_as_such(self, detector):
        report = calibrate_policy(
            synthetic_benign_corpus(100),
            detector.privileges_for,
            detector.boundaries_for,
        )
        assert any("unmeasured" in c for c in report.caveats)

    def test_applying_calibration_replaces_the_placeholders(self, detector):
        report = calibrate_policy(
            synthetic_benign_corpus(800, seed=1),
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )

        before = detector.security_policies["max_privileges"]
        detector.apply_calibration(report)

        assert detector.calibration is report
        assert detector.security_policies["max_privileges"] == report.max_privileges
        assert (
            detector.security_policies["boundary_policy"]["max_boundaries"]
            == report.max_boundaries
        )
        print(f"\nmax_privileges: {before} (placeholder) -> {report.max_privileges}")

    def test_calibrated_detector_still_catches_the_escalation_sequence(self):
        """
        Calibration must not be a way of making the detector permissive. The
        cloud-escape sequence must still be flagged under derived thresholds.
        """
        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())
        detector = ComposabilityDetector(verifier)

        report = calibrate_policy(
            synthetic_benign_corpus(800, seed=1),
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )
        detector.apply_calibration(report)

        sequence = [
            ("file_read", "/app/data.json"),
            ("api_call", "internal-api.example.com/health"),
            ("metadata_query", "169.254.169.254/latest/meta-data/"),
            ("credential_use", "sts.amazonaws.com/assume-role"),
        ]
        attestations = [
            service.attest_action(a, t, {"step": i})
            for i, (a, t) in enumerate(sequence, 1)
        ]

        attack = detector.analyze_action_sequence(attestations)

        assert attack is not None
        assert attack.blamed_sequence, "must name the flagged prefix"
        print(f"\ncalibrated detector flagged: {attack.violation_type.value}")

    def test_placeholder_threshold_was_measurably_wrong(self, detector):
        """
        The reason calibration was worth doing, stated as a number.

        The shipped placeholder was max_privileges = 3. Benign traffic in this
        corpus routinely reaches 4 cumulative privileges, so the placeholder sat
        *below* normal and flagged benign sequences. Calibration did not merely
        justify the old number, it corrected it.
        """
        corpus = synthetic_benign_corpus(800, seed=1)
        holdout = synthetic_benign_corpus(200, seed=2)

        derived = calibrate_policy(
            corpus,
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )

        # Score the holdout against the original hand-written thresholds.
        placeholder = calibrate_policy(
            corpus,
            detector.privileges_for,
            detector.boundaries_for,
            candidate_privileges=detector.known_privileges(),
        )
        placeholder.max_privileges = 3
        placeholder.max_boundaries = 2
        placeholder = measure_holdout_false_positives(
            placeholder, holdout, detector.privileges_for, detector.boundaries_for
        )

        derived = measure_holdout_false_positives(
            derived, holdout, detector.privileges_for, detector.boundaries_for
        )

        assert placeholder.holdout_false_positive_rate > 0.0
        assert derived.holdout_false_positive_rate == 0.0
        assert derived.max_privileges > 3

        print(
            f"\nplaceholder max_privileges=3 -> FP rate "
            f"{placeholder.holdout_false_positive_rate * 100:.1f}% on benign holdout"
            f"\nderived     max_privileges={derived.max_privileges} -> FP rate "
            f"{derived.holdout_false_positive_rate * 100:.1f}%"
        )

    def test_percentile_choice_is_a_visible_parameter(self, detector):
        """
        A lower percentile tightens the threshold. Exposing it means a
        deployment defends its own tradeoff instead of inheriting ours.
        """
        corpus = synthetic_benign_corpus(800, seed=1)

        loose = calibrate_policy(
            corpus, detector.privileges_for, detector.boundaries_for, percentile=100.0
        )
        tight = calibrate_policy(
            corpus, detector.privileges_for, detector.boundaries_for, percentile=50.0
        )

        assert tight.max_privileges <= loose.max_privileges
