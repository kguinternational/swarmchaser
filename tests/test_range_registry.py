"""
Evaluation of the obligated-range registry against real operator-published data.

Everything here runs against the cached copies of the actual files OpenAI
publishes for its crawler egress ranges (data/registries/). Those files are the
real-world instance of the registry that gap detection depends on, so their
measured properties bound what the method can claim.

The clock is pinned to 2026-09-11 so the reported staleness figures stay
reproducible; without that, every number in the report would drift daily.
"""

from datetime import datetime, timezone

import pytest

from src.attribution import (
    ActionAttestationService,
    ForensicVerifier,
    GapDetector,
    ObservedEvent,
    Confidence,
    RangeEntry,
    SignedRegistry,
    audit_registries,
    load_published_ranges,
    load_bundled_openai_registries,
    verify_chain,
)


# Pinned so measured staleness is deterministic and citable.
AUDIT_CLOCK = datetime(2026, 9, 11, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def real_audit():
    return load_bundled_openai_registries(now=AUDIT_CLOCK)


class TestRealPublishedRegistry:
    """What the operator's own files actually say."""

    def test_both_files_load(self, real_audit):
        assert set(real_audit.sources) == {"gptbot", "searchbot"}
        assert len(real_audit.entries) == 60

        print("\n" + real_audit.summary())

    def test_published_snapshots_are_stale(self, real_audit):
        """
        The operator instructs consumers to refetch because ranges rotate.
        The published snapshots are themselves months old, which is the
        finding: staleness is not hypothetical, it is the default state.
        """
        staleness = real_audit.staleness_by_source()

        assert staleness["gptbot"] > 300
        assert staleness["searchbot"] > 240

        print(
            f"\nStaleness at {AUDIT_CLOCK.date()}: "
            f"gptbot={staleness['gptbot']}d searchbot={staleness['searchbot']}d"
        )

    def test_products_share_prefixes_so_attribution_is_ambiguous(self, real_audit):
        """
        Six prefixes appear in both files. An address inside one of them cannot
        be attributed to a single product, which caps attribution granularity
        below what the signature scheme suggests.
        """
        shared = real_audit.shared_prefixes()
        assert len(shared) == 6

        for cidr, products in shared.items():
            assert len(products) > 1, cidr

        ambiguous = real_audit.ambiguous_address_count()
        total = real_audit.total_addresses()
        assert ambiguous > 0
        assert ambiguous < total

        print(
            f"\nAmbiguous: {ambiguous:,} of {total:,} addresses "
            f"({ambiguous / total * 100:.1f}%) across {len(shared)} shared prefixes"
        )

    def test_overlap_means_naive_address_sum_overcounts(self, real_audit):
        """Summing prefix sizes double-counts the shared ranges."""
        assert real_audit.naive_address_sum() > real_audit.total_addresses()

    def test_most_prefixes_sit_in_reassignable_cloud_space(self, real_audit):
        """
        Multi-tenant space can be reassigned without the operator republishing,
        so a stale entry can point at somebody else's host.
        """
        cloud = real_audit.cloud_hosted_count()
        assert cloud > len(real_audit.entries) / 2

        print(f"\nCloud-hosted prefixes: {cloud} of {len(real_audit.entries)}")

    def test_no_real_prefix_earns_high_confidence(self, real_audit):
        """
        The headline registry result. Against the operator's own published
        data, every prefix is degraded by staleness, sharing or tenancy. So no
        gap derived from this registry is assertable as a finding.
        """
        breakdown = real_audit.confidence_breakdown()

        assert breakdown.get("high", 0) == 0
        assert breakdown.get("low", 0) > 0

        print(f"\nConfidence breakdown: {breakdown}")


class TestConfidenceDegradation:
    """The confidence rule itself, on controlled inputs."""

    def _entry(self, **kw) -> RangeEntry:
        base = dict(
            cidr="203.0.113.0/24",
            operator="testlab",
            product="agent",
            published_utc=AUDIT_CLOCK,
        )
        base.update(kw)
        return RangeEntry(**base)

    def test_fresh_dedicated_non_cloud_range_is_high(self):
        entry = self._entry()
        assert entry.confidence(AUDIT_CLOCK) == Confidence.HIGH

    def test_one_degrading_factor_gives_medium(self):
        stale = self._entry(published_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert stale.confidence(AUDIT_CLOCK) == Confidence.MEDIUM

        shared = self._entry(shared_with=("other_product",))
        assert shared.confidence(AUDIT_CLOCK) == Confidence.MEDIUM

        cloud = self._entry(cloud_tenancy="azure")
        assert cloud.confidence(AUDIT_CLOCK) == Confidence.MEDIUM

    def test_two_or_more_factors_gives_low(self):
        entry = self._entry(
            published_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            shared_with=("other_product",),
        )
        assert entry.confidence(AUDIT_CLOCK) == Confidence.LOW

    def test_staleness_threshold_is_a_stated_assumption(self):
        """
        90 days is a judgement call, not a measurement. It is a parameter so a
        deployment can defend its own choice rather than inherit ours.
        """
        entry = self._entry(published_utc=datetime(2026, 6, 1, tzinfo=timezone.utc))

        assert entry.confidence(AUDIT_CLOCK, stale_after_days=90) == Confidence.MEDIUM
        assert entry.confidence(AUDIT_CLOCK, stale_after_days=365) == Confidence.HIGH


class TestSharedEgressHandling:
    """
    NAT and shared egress are the dominant false-positive source. The design
    response is not to suppress the gap but to refuse to assert it.
    """

    def test_shared_prefix_is_registered_at_lowest_confidence(self):
        entries_a, pub_a = load_published_ranges(
            "data/registries/openai-gptbot-2025-10-30.json", "openai", "gptbot"
        )
        entries_b, pub_b = load_published_ranges(
            "data/registries/openai-searchbot-2026-01-02.json", "openai", "searchbot"
        )
        audit = audit_registries(
            [(entries_a, pub_a, "gptbot"), (entries_b, pub_b, "searchbot")],
            now=AUDIT_CLOCK,
        )

        detector = GapDetector(ForensicVerifier())
        registered = detector.register_from_audit(audit)

        # 60 entries collapse to 54 distinct CIDRs because 6 are claimed twice.
        assert registered == 54

        print(f"\nRegistered {registered} distinct CIDRs from 60 published entries")

    def test_gap_from_real_range_carries_its_degrading_factors(self):
        audit = load_bundled_openai_registries(now=AUDIT_CLOCK)
        detector = GapDetector(ForensicVerifier())
        detector.register_from_audit(audit)

        # Pick a real published address inside a registered prefix.
        first_cidr = audit.entries[0].cidr
        import ipaddress

        probe_ip = str(next(ipaddress.ip_network(first_cidr, strict=False).hosts()))

        report = detector.scan(
            [
                ObservedEvent(
                    source_ip=probe_ip,
                    action_type="wiki_edit",
                    target="de.example.org/wiki/Page",
                    timestamp_ms=1_780_000_000_000,
                )
            ]
        )

        assert report.gap_count == 1
        gap = report.gaps[0]

        assert gap.confidence in {"low", "medium"}
        assert gap.degrading_factors, "a degraded gap must say why"
        assert not gap.is_assertable

        print(f"\nGap confidence={gap.confidence} factors={gap.degrading_factors}")

    def test_real_registry_yields_no_assertable_gaps(self):
        """
        Consequence of the registry audit: with real published data, gap
        detection produces triage leads only. This is the honest ceiling on
        the method as deployable today.
        """
        audit = load_bundled_openai_registries(now=AUDIT_CLOCK)
        detector = GapDetector(ForensicVerifier())
        detector.register_from_audit(audit)

        import ipaddress

        events = []
        for i, entry in enumerate(audit.entries[:10]):
            host = next(ipaddress.ip_network(entry.cidr, strict=False).hosts())
            events.append(
                ObservedEvent(
                    source_ip=str(host),
                    action_type="api_call",
                    target=f"example.org/resource/{i}",
                    timestamp_ms=1_780_000_000_000 + i * 1000,
                )
            )

        report = detector.scan(events)

        assert report.gap_count == len(events)
        assert report.assertable_gaps == []
        assert any("assertable" in c for c in report.caveats)

        print("\n" + report.summary())


class TestSignedRegistryChain:
    """
    A registry the operator can silently rewrite is not evidence. These assert
    the three tamper modes are actually detected, rather than assumed.
    """

    def _populated(self) -> SignedRegistry:
        reg = SignedRegistry("openai")
        reg.append("20.42.10.0/24", "2026-01-01T00:00:00+00:00")
        reg.append("52.230.152.0/24", "2026-02-01T00:00:00+00:00")
        reg.append("172.182.204.0/24", "2026-03-01T00:00:00+00:00")
        return reg

    def test_intact_chain_verifies(self):
        reg = self._populated()
        verdict = verify_chain(reg.export(), reg.public_key_pem())

        assert verdict.valid
        assert verdict.checked == 3
        print(f"\n{verdict.summary()}")

    def test_rewritten_cidr_is_detected(self):
        """Retroactively disowning a range must not verify."""
        reg = self._populated()
        exported = reg.export()
        exported[1]["cidr"] = "10.0.0.0/8"

        verdict = verify_chain(exported, reg.public_key_pem())

        assert not verdict.valid
        assert verdict.failure_index == 1
        print(f"\n{verdict.summary()}")

    def test_removed_entry_is_detected(self):
        """Truncating history breaks the hash linkage."""
        reg = self._populated()
        exported = reg.export()
        del exported[1]

        verdict = verify_chain(exported, reg.public_key_pem())

        assert not verdict.valid
        print(f"\n{verdict.summary()}")

    def test_reordered_chain_is_detected(self):
        reg = self._populated()
        exported = reg.export()
        exported[0], exported[1] = exported[1], exported[0]

        verdict = verify_chain(exported, reg.public_key_pem())

        assert not verdict.valid
        print(f"\n{verdict.summary()}")

    def test_forged_signature_is_detected(self):
        """A different operator's key cannot vouch for this chain."""
        reg = self._populated()
        other = SignedRegistry("impostor")

        verdict = verify_chain(reg.export(), other.public_key_pem())

        assert not verdict.valid
        print(f"\n{verdict.summary()}")

    def test_malformed_cidr_rejected_at_append(self):
        """A bad registry entry must fail loudly, not silently disable detection."""
        reg = SignedRegistry("openai")
        with pytest.raises(ValueError):
            reg.append("not-a-cidr", "2026-01-01T00:00:00+00:00")

    def test_withdrawal_is_an_append_not_a_deletion(self):
        """
        Append-only means the history of what was claimed survives. A verifier
        can see that a range was once claimed and later withdrawn.
        """
        reg = SignedRegistry("openai")
        reg.append("20.42.10.0/24", "2026-01-01T00:00:00+00:00")
        reg.append("20.42.10.0/24", "2026-06-01T00:00:00+00:00")

        exported = reg.export()
        assert len(exported) == 2
        assert verify_chain(exported, reg.public_key_pem()).valid

        claimed = [e["cidr"] for e in exported]
        assert claimed.count("20.42.10.0/24") == 2


class TestRegistryBoundsGapDetection:
    """The registry is the ceiling on gap quality. These state that plainly."""

    def test_unregistered_egress_produces_no_gap(self):
        """
        Restates the method's central limit against the real registry: an
        adversary egressing from space the operator never published is
        invisible regardless of registry quality.
        """
        audit = load_bundled_openai_registries(now=AUDIT_CLOCK)
        detector = GapDetector(ForensicVerifier())
        detector.register_from_audit(audit)

        # 198.51.100.0/24 is TEST-NET-2, in no published range.
        events = [
            ObservedEvent(
                source_ip="198.51.100.7",
                action_type="wiki_edit",
                target=f"de.example.org/wiki/Page{i}",
                timestamp_ms=1_780_000_000_000 + i * 1000,
            )
            for i in range(500)
        ]

        report = detector.scan(events)

        assert report.gap_count == 0
        assert report.out_of_scope == 500
        print("\n500 unregistered-egress events -> 0 gaps (method blind here)")

    def test_attested_traffic_from_real_range_is_not_flagged(self):
        """No false positive when the obligation is actually met."""
        audit = load_bundled_openai_registries(now=AUDIT_CLOCK)

        service = ActionAttestationService("openai", "gpt-4")
        verifier = ForensicVerifier()
        verifier.register_lab_public_key("openai", service.get_public_key_pem())

        detector = GapDetector(verifier)
        detector.register_from_audit(audit)

        import ipaddress

        host = str(next(ipaddress.ip_network(audit.entries[0].cidr, strict=False).hosts()))

        events = []
        for i in range(50):
            target = f"example.org/resource/{i}"
            att = service.attest_action("api_call", target, {"i": i})
            events.append(
                ObservedEvent(
                    source_ip=host,
                    action_type="api_call",
                    target=target,
                    timestamp_ms=1_780_000_000_000 + i * 1000,
                    attestation=att,
                )
            )

        report = detector.scan(events)

        assert report.attested == 50
        assert report.gap_count == 0
        print("\n50 properly attested events from a real range -> 0 gaps")
