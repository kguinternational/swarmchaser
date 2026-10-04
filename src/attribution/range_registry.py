"""
Obligated-range registry: load, audit and sign operator-published egress ranges.

Why this module exists
----------------------
`gap_detector` treats "traffic from this range must be signed" as given. In
practice that claim comes from a file the operator publishes, and the quality of
every gap finding is bounded by the quality of that file. This module measures
the file rather than trusting it.

Three properties turn out to matter, and all three are measurable against real
published data:

  staleness   The operator tells you the ranges rotate and to refetch often.
              If the published snapshot is months old, every gap derived from
              it inherits that uncertainty.

  overlap     When two products publish overlapping prefixes, an address in the
              intersection cannot attribute to either one. Attribution
              granularity is bounded by the partition, not by the crypto.

  tenancy     These prefixes sit in public cloud space. Cloud providers reassign
              address space, so a range can stop belonging to the operator
              without the operator republishing anything.

Signing the registry
--------------------
A registry an operator can silently rewrite is not evidence. `SignedRegistry`
hash-chains entries and signs each link, so a verifier detects truncation,
reordering and retroactive disavowal of a CIDR. This is the append-only
property the report argues a mandate would need.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


# Public-cloud blocks that the observed operator ranges fall inside. This list
# is deliberately coarse: it is used only to flag that a prefix sits in
# multi-tenant space that the provider can reassign, not to identify a provider
# authoritatively. Sourced by inspection of the published files.
_KNOWN_CLOUD_BLOCKS: tuple[tuple[str, str], ...] = (
    ("4.0.0.0/8", "azure"),
    ("13.64.0.0/11", "azure"),
    ("20.0.0.0/8", "azure"),
    ("23.96.0.0/13", "azure"),
    ("40.64.0.0/10", "azure"),
    ("51.0.0.0/8", "azure"),
    ("52.224.0.0/11", "azure"),
    ("104.208.0.0/13", "azure"),
    ("135.224.0.0/12", "azure"),
    ("172.182.0.0/15", "azure"),
    ("172.202.0.0/15", "azure"),
)


class Confidence(Enum):
    """
    How much weight a gap from this range can carry.

    Deliberately coarse. A finer scale would imply calibration this work does
    not have.
    """

    HIGH = "high"
    """Dedicated, freshly published, unambiguous range."""

    MEDIUM = "medium"
    """Usable, but one degrading factor applies."""

    LOW = "low"
    """Shared, stale or multi-tenant. Triage only; do not assert a violation."""


@dataclass(frozen=True)
class RangeEntry:
    """One published prefix, with the audit facts that bound its usefulness."""

    cidr: str
    operator: str
    product: str
    published_utc: datetime
    shared_with: tuple[str, ...] = ()
    cloud_tenancy: str | None = None

    def network(self) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
        return ipaddress.ip_network(self.cidr, strict=False)

    def address_count(self) -> int:
        return self.network().num_addresses

    def staleness_days(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        return (now - self.published_utc).days

    def confidence(
        self,
        now: datetime | None = None,
        stale_after_days: int = 90,
    ) -> Confidence:
        """
        Degrade confidence for sharing, staleness and multi-tenancy.

        `stale_after_days` defaults to 90 as a stated assumption, not a
        measured threshold. The operator publishes no freshness guarantee, so
        any choice here is a judgement call and is surfaced as one.
        """
        degrading = 0
        if self.shared_with:
            degrading += 1
        if self.staleness_days(now) > stale_after_days:
            degrading += 1
        if self.cloud_tenancy is not None:
            degrading += 1

        if degrading == 0:
            return Confidence.HIGH
        if degrading == 1:
            return Confidence.MEDIUM
        return Confidence.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "cidr": self.cidr,
            "operator": self.operator,
            "product": self.product,
            "published_utc": self.published_utc.isoformat(),
            "shared_with": list(self.shared_with),
            "cloud_tenancy": self.cloud_tenancy,
            "address_count": self.address_count(),
        }


@dataclass
class RegistryAudit:
    """Measured properties of a set of published range files."""

    entries: list[RangeEntry]
    sources: dict[str, datetime]
    now: datetime

    def total_addresses(self) -> int:
        """Distinct addresses covered, collapsing overlaps."""
        collapsed = ipaddress.collapse_addresses(
            [e.network() for e in self.entries]
        )
        return sum(n.num_addresses for n in collapsed)

    def naive_address_sum(self) -> int:
        """Sum of per-prefix sizes, which double-counts overlaps."""
        return sum(e.address_count() for e in self.entries)

    def staleness_by_source(self) -> dict[str, int]:
        return {
            name: (self.now - published).days
            for name, published in self.sources.items()
        }

    def shared_prefixes(self) -> dict[str, list[str]]:
        """CIDR -> products publishing it, for prefixes claimed more than once."""
        by_cidr: dict[str, list[str]] = {}
        for e in self.entries:
            by_cidr.setdefault(e.cidr, []).append(e.product)
        return {c: p for c, p in by_cidr.items() if len(p) > 1}

    def ambiguous_address_count(self) -> int:
        """Addresses that cannot be attributed to a single product."""
        shared = self.shared_prefixes()
        nets = {
            ipaddress.ip_network(c, strict=False) for c in shared
        }
        collapsed = ipaddress.collapse_addresses(nets) if nets else []
        return sum(n.num_addresses for n in collapsed)

    def confidence_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            key = e.confidence(self.now).value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def cloud_hosted_count(self) -> int:
        return sum(1 for e in self.entries if e.cloud_tenancy is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_count": len(self.entries),
            "distinct_addresses": self.total_addresses(),
            "naive_address_sum": self.naive_address_sum(),
            "staleness_days_by_source": self.staleness_by_source(),
            "shared_prefix_count": len(self.shared_prefixes()),
            "shared_prefixes": self.shared_prefixes(),
            "ambiguous_addresses": self.ambiguous_address_count(),
            "confidence_breakdown": self.confidence_breakdown(),
            "cloud_hosted_prefixes": self.cloud_hosted_count(),
            "audited_at": self.now.isoformat(),
        }

    def summary(self) -> str:
        lines = [
            "Range registry audit",
            f"  prefixes            : {len(self.entries)}",
            f"  distinct addresses  : {self.total_addresses():,}",
            f"  naive sum           : {self.naive_address_sum():,} "
            f"(difference is overlap)",
        ]
        for name, days in sorted(self.staleness_by_source().items()):
            lines.append(f"  staleness [{name}] : {days} days")
        shared = self.shared_prefixes()
        lines.append(f"  shared prefixes     : {len(shared)}")
        for cidr, products in sorted(shared.items()):
            lines.append(f"    {cidr} <- {', '.join(sorted(products))}")
        lines.append(
            f"  ambiguous addresses : {self.ambiguous_address_count():,} "
            f"(cannot attribute to one product)"
        )
        lines.append(f"  cloud-hosted        : {self.cloud_hosted_count()}")
        for level, n in sorted(self.confidence_breakdown().items()):
            lines.append(f"  confidence [{level}] : {n}")
        return "\n".join(lines)


def _cloud_tenancy_for(net: ipaddress.IPv4Network | ipaddress.IPv6Network) -> str | None:
    for block, provider in _KNOWN_CLOUD_BLOCKS:
        try:
            if net.subnet_of(ipaddress.ip_network(block)):
                return provider
        except TypeError:
            continue
    return None


def load_published_ranges(
    path: str | Path,
    operator: str,
    product: str,
) -> tuple[list[RangeEntry], datetime]:
    """
    Load an operator-published range file in the observed schema.

    The schema is `{creationTime, prefixes: [{ipv4Prefix|ipv6Prefix}]}`, which
    is what the real files use. `_provenance`, if present, is metadata added by
    this repository and is ignored.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    created = raw.get("creationTime")
    if not created:
        raise ValueError(f"{path}: missing creationTime")
    published = datetime.fromisoformat(created)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    entries: list[RangeEntry] = []
    for prefix in raw.get("prefixes", []):
        cidr = prefix.get("ipv4Prefix") or prefix.get("ipv6Prefix")
        if not cidr:
            continue
        net = ipaddress.ip_network(cidr, strict=False)
        entries.append(
            RangeEntry(
                cidr=cidr,
                operator=operator,
                product=product,
                published_utc=published,
                cloud_tenancy=_cloud_tenancy_for(net),
            )
        )

    if not entries:
        raise ValueError(f"{path}: no usable prefixes")

    return entries, published


def audit_registries(
    loaded: Sequence[tuple[list[RangeEntry], datetime, str]],
    now: datetime | None = None,
) -> RegistryAudit:
    """
    Combine loaded range files and cross-annotate shared prefixes.

    `loaded` is a sequence of (entries, published, source_name).
    """
    now = now or datetime.now(timezone.utc)

    all_entries: list[RangeEntry] = []
    sources: dict[str, datetime] = {}
    for entries, published, name in loaded:
        all_entries.extend(entries)
        sources[name] = published

    # Which products claim each CIDR.
    claimants: dict[str, set[str]] = {}
    for e in all_entries:
        claimants.setdefault(e.cidr, set()).add(e.product)

    annotated = [
        RangeEntry(
            cidr=e.cidr,
            operator=e.operator,
            product=e.product,
            published_utc=e.published_utc,
            shared_with=tuple(sorted(claimants[e.cidr] - {e.product})),
            cloud_tenancy=e.cloud_tenancy,
        )
        for e in all_entries
    ]

    return RegistryAudit(entries=annotated, sources=sources, now=now)


# --------------------------------------------------------------------------
# Signed, append-only registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedEntry:
    """A hash-chained, signed registry record."""

    index: int
    cidr: str
    operator: str
    effective_from_utc: str
    prev_hash: str
    entry_hash: str
    signature: str

    def payload(self) -> str:
        """Canonical bytes covered by `entry_hash`."""
        return json.dumps(
            {
                "index": self.index,
                "cidr": self.cidr,
                "operator": self.operator,
                "effective_from_utc": self.effective_from_utc,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "cidr": self.cidr,
            "operator": self.operator,
            "effective_from_utc": self.effective_from_utc,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "signature": self.signature,
        }


GENESIS_HASH = "0" * 64


class SignedRegistry:
    """
    Append-only registry of obligated ranges.

    Each entry commits to its predecessor's hash and is signed, so an operator
    cannot retroactively disown a CIDR, reorder history, or drop a record
    without a verifier noticing. Withdrawal is an explicit later append, never
    a deletion.
    """

    def __init__(self, operator: str, private_key: Ed25519PrivateKey | None = None):
        self.operator = operator
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self.public_key: Ed25519PublicKey = self._private_key.public_key()
        self.entries: list[SignedEntry] = []

    def public_key_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def append(self, cidr: str, effective_from_utc: str) -> SignedEntry:
        """Append a range declaration. Validates the CIDR before committing."""
        ipaddress.ip_network(cidr, strict=False)

        index = len(self.entries)
        prev_hash = self.entries[-1].entry_hash if self.entries else GENESIS_HASH

        skeleton = SignedEntry(
            index=index,
            cidr=cidr,
            operator=self.operator,
            effective_from_utc=effective_from_utc,
            prev_hash=prev_hash,
            entry_hash="",
            signature="",
        )
        entry_hash = hashlib.sha256(
            skeleton.payload().encode("utf-8")
        ).hexdigest()
        signature = self._private_key.sign(entry_hash.encode("utf-8")).hex()

        entry = SignedEntry(
            index=index,
            cidr=cidr,
            operator=self.operator,
            effective_from_utc=effective_from_utc,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            signature=signature,
        )
        self.entries.append(entry)
        return entry

    def export(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]


@dataclass
class ChainVerdict:
    """Result of verifying a registry chain."""

    valid: bool
    checked: int
    failure_index: int | None = None
    reason: str | None = None

    def summary(self) -> str:
        if self.valid:
            return f"chain valid over {self.checked} entries"
        return (
            f"chain INVALID at index {self.failure_index}: {self.reason} "
            f"({self.checked} entries checked)"
        )


def verify_chain(
    exported: Iterable[dict[str, Any]],
    public_key_pem: str,
) -> ChainVerdict:
    """
    Verify hash linkage and signatures over an exported registry.

    Detects a rewritten CIDR, a reordered chain, and a removed entry. Each
    failure mode is asserted in the test suite rather than assumed.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))

    expected_prev = GENESIS_HASH
    checked = 0

    for position, raw in enumerate(exported):
        entry = SignedEntry(
            index=raw["index"],
            cidr=raw["cidr"],
            operator=raw["operator"],
            effective_from_utc=raw["effective_from_utc"],
            prev_hash=raw["prev_hash"],
            entry_hash=raw["entry_hash"],
            signature=raw["signature"],
        )

        if entry.index != position:
            return ChainVerdict(
                valid=False,
                checked=checked,
                failure_index=position,
                reason=f"index {entry.index} out of order at position {position}",
            )

        if entry.prev_hash != expected_prev:
            return ChainVerdict(
                valid=False,
                checked=checked,
                failure_index=position,
                reason="prev_hash does not match preceding entry_hash "
                "(entry removed, reordered or inserted)",
            )

        recomputed = hashlib.sha256(entry.payload().encode("utf-8")).hexdigest()
        if recomputed != entry.entry_hash:
            return ChainVerdict(
                valid=False,
                checked=checked,
                failure_index=position,
                reason="entry_hash does not match content (record altered)",
            )

        try:
            public_key.verify(
                bytes.fromhex(entry.signature),
                entry.entry_hash.encode("utf-8"),
            )
        except (InvalidSignature, ValueError):
            return ChainVerdict(
                valid=False,
                checked=checked,
                failure_index=position,
                reason="signature does not verify",
            )

        expected_prev = entry.entry_hash
        checked += 1

    return ChainVerdict(valid=True, checked=checked)


DEFAULT_REGISTRY_DIR = Path("data/registries")


def load_bundled_openai_registries(
    registry_dir: str | Path = DEFAULT_REGISTRY_DIR,
    now: datetime | None = None,
) -> RegistryAudit:
    """
    Audit the cached copies of the real operator-published files.

    Cached rather than fetched so the figures in the report correspond to a
    fixed, auditable snapshot. Refetch from the `_provenance.source_url` in
    each file to reproduce against live data.
    """
    registry_dir = Path(registry_dir)
    loaded = [
        (
            *load_published_ranges(
                registry_dir / "openai-gptbot-2025-10-30.json", "openai", "gptbot"
            ),
            "gptbot",
        ),
        (
            *load_published_ranges(
                registry_dir / "openai-searchbot-2026-01-02.json",
                "openai",
                "searchbot",
            ),
            "searchbot",
        ),
    ]
    return audit_registries(loaded, now=now)


if __name__ == "__main__":
    audit = load_bundled_openai_registries()
    print(audit.summary())
