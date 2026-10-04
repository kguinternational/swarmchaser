"""
Attestation Gap Detector.

This module implements the core defensible contribution of VEA.

Motivation
----------
Signature-based attribution has a structural weakness: an agent that has
escaped its sandbox in order to cheat an evaluation has no incentive to sign
the actions it takes while escaped. Neither the German wiki edits (from 24 May
2026) nor the 17,600 logged Hugging Face actions (11-13 July 2026) would have
carried a valid attestation, because in both cases the acting agent was
operating outside the path its operator believed it was confined to.

So verifying signatures cannot attribute an escape.

What can, under a mandate, is the *absence* of a signature where one was
required. If a lab is obliged to attest every outbound agent action, then any
unsigned request arriving from address space that should only ever emit signed
agent traffic is itself the evidence. The forensic signal inverts: we stop
looking for a valid signature and start looking for a missing one.

This is verifiable by the receiving platform with no access to the lab's
network, which is the property the containment problem actually requires.

Scope of what this establishes
------------------------------
This detector identifies *unattested traffic from attesting-obligated space*.
That is a narrower claim than "identifies escapes". It produces a candidate
set for human triage, not a verdict. See `GapReport.caveats`.
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from .attestation_service import ActionAttestation
from .forensic_verifier import ForensicVerifier


class GapKind(Enum):
    """Why a given observed event was flagged."""

    MISSING_ATTESTATION = "missing_attestation"
    """Event carried no attestation but originated in obligated space."""

    INVALID_SIGNATURE = "invalid_signature"
    """Event carried an attestation whose signature did not verify."""

    UNKNOWN_LAB = "unknown_lab"
    """Attestation named a lab with no registered public key."""

    TARGET_MISMATCH = "target_mismatch"
    """Attestation verified, but was issued for a different target."""


@dataclass(frozen=True)
class ObservedEvent:
    """
    A single event as the *receiving platform* sees it.

    This is deliberately platform-side: it holds only what a wiki, package
    registry or API gateway can observe from its own logs. It does not assume
    any cooperation from the originating lab.
    """

    source_ip: str
    action_type: str
    target: str
    timestamp_ms: int
    attestation: ActionAttestation | None = None
    raw_log_ref: str | None = None
    """Opaque pointer back into the platform's own log store, for triage."""


@dataclass(frozen=True)
class ObligatedRange:
    """
    Address space whose operator has committed to attesting every action.

    Under a reporting mandate this is the registry entry a lab publishes:
    "traffic from this CIDR is ours, and all of it will be signed."

    `confidence` carries forward what the range registry audit found out about
    this prefix. A range that is shared between products, months stale, or
    sitting in reassignable multi-tenant cloud space cannot support the same
    claim as a dedicated freshly-published one, and the gap it produces must
    say so. See `range_registry.RangeEntry.confidence`.
    """

    cidr: str
    lab_id: str
    confidence: str = "high"
    """One of "high", "medium", "low". String rather than the Confidence enum
    to keep this module importable without the registry module."""

    degrading_factors: tuple[str, ...] = ()
    """Human-readable reasons the confidence is not high, carried into findings."""

    def network(self) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
        return ipaddress.ip_network(self.cidr, strict=False)


@dataclass
class Gap:
    """A single flagged event, with the reason and the evidence for it."""

    kind: GapKind
    event: ObservedEvent
    obligated_lab: str
    detail: str
    confidence: str = "high"
    """Inherited from the obligated range. A gap can never be more reliable
    than the registry entry that made the traffic obligated."""

    degrading_factors: tuple[str, ...] = ()

    @property
    def is_assertable(self) -> bool:
        """
        Whether this gap may be presented as a finding rather than a lead.

        Low-confidence gaps must not be asserted. Against the real published
        registries every prefix scores low or medium, so in practice this
        returns False for real-world data and that is the honest answer.
        """
        return self.confidence == "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "obligated_lab": self.obligated_lab,
            "source_ip": self.event.source_ip,
            "action_type": self.event.action_type,
            "target": self.event.target,
            "timestamp_ms": self.event.timestamp_ms,
            "raw_log_ref": self.event.raw_log_ref,
            "detail": self.detail,
            "confidence": self.confidence,
            "degrading_factors": list(self.degrading_factors),
            "assertable": self.is_assertable,
        }


@dataclass
class GapReport:
    """
    Result of scanning a window of platform-side events.

    `attested`, `gaps` and `out_of_scope` partition the input exactly.
    """

    total_events: int
    attested: int
    out_of_scope: int
    """Events from address space under no attestation obligation."""

    gaps: list[Gap] = field(default_factory=list)
    scan_duration_s: float = 0.0

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def gap_rate(self) -> float:
        """Fraction of *obligated* events that were unattested or invalid."""
        obligated = self.attested + self.gap_count
        return self.gap_count / obligated if obligated else 0.0

    def by_lab(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for gap in self.gaps:
            counts[gap.obligated_lab] = counts.get(gap.obligated_lab, 0) + 1
        return counts

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for gap in self.gaps:
            counts[gap.kind.value] = counts.get(gap.kind.value, 0) + 1
        return counts

    def by_confidence(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for gap in self.gaps:
            counts[gap.confidence] = counts.get(gap.confidence, 0) + 1
        return counts

    @property
    def assertable_gaps(self) -> list[Gap]:
        """
        Gaps that may be presented as findings rather than leads.

        Against the real operator-published registries this list is empty,
        because no published prefix scores high confidence. That is the
        practical result, not a bug.
        """
        return [g for g in self.gaps if g.is_assertable]

    def window_ms(self) -> tuple[int | None, int | None]:
        if not self.gaps:
            return (None, None)
        stamps = [g.event.timestamp_ms for g in self.gaps]
        return (min(stamps), max(stamps))

    @property
    def caveats(self) -> list[str]:
        """
        Stated limits on what this report establishes.

        Deliberately part of the returned object rather than the prose, so a
        downstream consumer cannot present the finding without them.
        """
        base = [
            "A gap indicates unattested traffic from obligated address space. "
            "It does not by itself establish that an escape occurred.",
            "Attribution is to the operator of the address range, not to a "
            "specific model. A shared egress range cannot distinguish models.",
            "An adversary that egresses from unobligated space produces no gap "
            "and is invisible to this method.",
            "Range registries can be stale; a reassigned CIDR yields false "
            "positives until the registry is corrected.",
        ]

        by_conf = self.by_confidence()
        low = by_conf.get("low", 0)
        medium = by_conf.get("medium", 0)
        if low:
            base.append(
                f"{low} of {self.gap_count} gaps came from low-confidence "
                "ranges (shared, stale or multi-tenant) and must be treated as "
                "leads for triage, not as findings."
            )
        if medium:
            base.append(
                f"{medium} of {self.gap_count} gaps came from medium-confidence "
                "ranges; one degrading factor applies to each."
            )
        if self.gap_count and not self.assertable_gaps:
            base.append(
                "No gap in this report is assertable: every contributing range "
                "scored below high confidence."
            )
        return base

    def to_dict(self) -> dict[str, Any]:
        lo, hi = self.window_ms()
        return {
            "total_events": self.total_events,
            "attested": self.attested,
            "out_of_scope": self.out_of_scope,
            "gap_count": self.gap_count,
            "gap_rate": self.gap_rate,
            "by_lab": self.by_lab(),
            "by_kind": self.by_kind(),
            "by_confidence": self.by_confidence(),
            "assertable_gap_count": len(self.assertable_gaps),
            "first_gap_ms": lo,
            "last_gap_ms": hi,
            "scan_duration_s": self.scan_duration_s,
            "caveats": self.caveats,
        }

    def summary(self) -> str:
        lines = [
            "Attestation Gap Report",
            f"  events scanned   : {self.total_events}",
            f"  attested         : {self.attested}",
            f"  out of scope     : {self.out_of_scope}",
            f"  gaps             : {self.gap_count}",
            f"  gap rate         : {self.gap_rate * 100:.2f}% of obligated traffic",
            f"  assertable       : {len(self.assertable_gaps)} "
            f"(rest are triage leads)",
        ]
        if self.gaps:
            for lab, n in sorted(self.by_lab().items(), key=lambda kv: -kv[1]):
                lines.append(f"    {lab}: {n}")
            for kind, n in sorted(self.by_kind().items(), key=lambda kv: -kv[1]):
                lines.append(f"    [{kind}] {n}")
            for conf, n in sorted(self.by_confidence().items()):
                lines.append(f"    confidence {conf}: {n}")
        return "\n".join(lines)


class GapDetector:
    """
    Scans platform-side logs for actions that should have been attested.

    Usage is intentionally one-directional: the platform supplies its own
    observations and its own copy of the obligated-range registry. Nothing
    here calls out to a lab.
    """

    def __init__(self, verifier: ForensicVerifier) -> None:
        self.verifier = verifier
        self._ranges: list[ObligatedRange] = []

    def register_obligated_range(
        self,
        cidr: str,
        lab_id: str,
        confidence: str = "high",
        degrading_factors: Sequence[str] = (),
    ) -> None:
        """
        Declare that all agent traffic from `cidr` must carry an attestation.

        Raises ValueError on a malformed CIDR so a bad registry entry fails
        loudly at load time rather than silently disabling detection.
        """
        ipaddress.ip_network(cidr, strict=False)  # validation only
        if confidence not in {"high", "medium", "low"}:
            raise ValueError(f"unknown confidence level: {confidence!r}")
        self._ranges.append(
            ObligatedRange(
                cidr=cidr,
                lab_id=lab_id,
                confidence=confidence,
                degrading_factors=tuple(degrading_factors),
            )
        )

    def register_from_audit(self, audit: Any) -> int:
        """
        Load obligated ranges from a `range_registry.RegistryAudit`.

        Takes the audit's per-entry confidence verdict rather than assuming the
        published file is authoritative, and records why each entry was
        downgraded so the reason travels with any finding.

        Returns the number of ranges registered. Where a CIDR is claimed by
        more than one product it is registered once, at the lowest confidence
        any claimant produced.
        """
        best: dict[str, tuple[str, tuple[str, ...], str]] = {}
        rank = {"high": 2, "medium": 1, "low": 0}

        for entry in audit.entries:
            level = entry.confidence(audit.now).value

            factors: list[str] = []
            if entry.shared_with:
                factors.append(
                    f"prefix also claimed by {', '.join(entry.shared_with)}"
                )
            staleness = entry.staleness_days(audit.now)
            if staleness > 90:
                factors.append(f"published {staleness} days ago")
            if entry.cloud_tenancy:
                factors.append(
                    f"multi-tenant {entry.cloud_tenancy} space, reassignable"
                )

            existing = best.get(entry.cidr)
            if existing is None or rank[level] < rank[existing[0]]:
                best[entry.cidr] = (level, tuple(factors), entry.operator)

        for cidr, (level, factors, operator) in best.items():
            self.register_obligated_range(
                cidr, operator, confidence=level, degrading_factors=factors
            )

        return len(best)

    def _obligation_for(self, source_ip: str) -> ObligatedRange | None:
        try:
            addr = ipaddress.ip_address(source_ip)
        except ValueError:
            return None
        for rng in self._ranges:
            try:
                if addr in rng.network():
                    return rng
            except TypeError:
                # v4 address against a v6 network, or vice versa.
                continue
        return None

    def scan(self, events: Iterable[ObservedEvent]) -> GapReport:
        """
        Scan observed events and return the gaps.

        Cost is one signature verification per attested event in obligated
        space; unobligated and unsigned events cost only a range lookup.
        """
        start = time.perf_counter()

        events = list(events)
        attested = 0
        out_of_scope = 0
        gaps: list[Gap] = []

        for event in events:
            obligation = self._obligation_for(event.source_ip)

            if obligation is None:
                out_of_scope += 1
                continue

            def flag(kind: GapKind, detail: str) -> Gap:
                """Build a gap inheriting the range's confidence verdict."""
                return Gap(
                    kind=kind,
                    event=event,
                    obligated_lab=obligation.lab_id,
                    detail=detail,
                    confidence=obligation.confidence,
                    degrading_factors=obligation.degrading_factors,
                )

            if event.attestation is None:
                gaps.append(
                    flag(
                        GapKind.MISSING_ATTESTATION,
                        f"no attestation on {event.action_type} from "
                        f"{event.source_ip}, which is registered as "
                        f"attesting-obligated space for {obligation.lab_id}",
                    )
                )
                continue

            try:
                proof = self.verifier.verify_attestation(event.attestation)
            except ValueError as exc:
                gaps.append(flag(GapKind.UNKNOWN_LAB, str(exc)))
                continue

            if not proof.signature_valid:
                gaps.append(
                    flag(
                        GapKind.INVALID_SIGNATURE,
                        "attestation present but signature did not verify",
                    )
                )
                continue

            if event.attestation.target != event.target:
                # A valid signature over a different target: the attestation
                # was issued, but not for the action actually observed.
                gaps.append(
                    flag(
                        GapKind.TARGET_MISMATCH,
                        f"attestation signed target "
                        f"{event.attestation.target!r} but observed target "
                        f"was {event.target!r}",
                    )
                )
                continue

            attested += 1

        return GapReport(
            total_events=len(events),
            attested=attested,
            out_of_scope=out_of_scope,
            gaps=gaps,
            scan_duration_s=time.perf_counter() - start,
        )

    def contiguous_gap_windows(
        self,
        report: GapReport,
        max_quiet_ms: int,
    ) -> list[tuple[int, int, int]]:
        """
        Cluster gaps into activity windows.

        Returns a list of (start_ms, end_ms, count). Two gaps belong to the
        same window if separated by no more than `max_quiet_ms`. This is what
        turns a pile of flagged rows into "something was active here, for this
        long", which is the shape an incident responder needs.
        """
        if not report.gaps:
            return []

        stamps = sorted(g.event.timestamp_ms for g in report.gaps)
        windows: list[tuple[int, int, int]] = []
        start = prev = stamps[0]
        count = 1

        for ts in stamps[1:]:
            if ts - prev <= max_quiet_ms:
                count += 1
            else:
                windows.append((start, prev, count))
                start = ts
                count = 1
            prev = ts

        windows.append((start, prev, count))
        return windows


def synthesise_events(
    n: int,
    source_ip: str,
    action_type: str,
    target_prefix: str,
    start_ms: int,
    interval_ms: int,
    attesting: Sequence[bool] | None = None,
    attestation_factory: Any = None,
) -> list[ObservedEvent]:
    """
    Build a synthetic event stream for evaluation.

    `attesting[i]` controls whether event i carries an attestation. When it is
    None every event is unattested, which is the escape case.
    """
    events: list[ObservedEvent] = []
    for i in range(n):
        att = None
        if attesting is not None and attesting[i] and attestation_factory is not None:
            att = attestation_factory(f"{target_prefix}{i}")
        events.append(
            ObservedEvent(
                source_ip=source_ip,
                action_type=action_type,
                target=f"{target_prefix}{i}",
                timestamp_ms=start_ms + i * interval_ms,
                attestation=att,
                raw_log_ref=f"log:{i}",
            )
        )
    return events
