"""
Verifiable Escape Attribution (VEA)

Two complementary mechanisms for attributing autonomous AI agent actions:

1. Signature-based attribution (`attestation_service`, `forensic_verifier`)
   works only when the acting agent cooperates by signing. It is a compliance
   mechanism, not a forensics one.

2. Attestation-gap detection (`gap_detector`) works when the agent does not
   cooperate, by treating a missing-but-required signature as the evidence.
   This is the mechanism that applies to an actual escape.

Both are verifiable by the receiving platform without access to the
originating lab's network.
"""

from .attestation_service import ActionAttestationService, ActionAttestation
from .forensic_verifier import (
    ForensicVerifier,
    AttributionProof,
    AttributionConfidence,
    UnknownSource,
)
from .composability_detector import (
    ComposabilityDetector,
    DecompositionAttack,
    ViolationType,
    SecurityState,
)
from .gap_detector import (
    GapDetector,
    GapReport,
    Gap,
    GapKind,
    ObservedEvent,
    ObligatedRange,
    synthesise_events,
)
from .range_registry import (
    Confidence,
    RangeEntry,
    RegistryAudit,
    SignedRegistry,
    SignedEntry,
    ChainVerdict,
    audit_registries,
    load_published_ranges,
    load_bundled_openai_registries,
    verify_chain,
)
from .key_custody import (
    CustodyAssurance,
    CustodyReport,
    SigningBackend,
    InProcessSigningBackend,
    ExternalSigningBackend,
    pkcs11_backend_stub,
)
from .policy_calibration import (
    CalibrationReport,
    Observation,
    calibrate_policy,
    measure_holdout_false_positives,
    synthetic_benign_corpus,
)
from .paac_integration import VEAMonitor, VEAConfig, create_vea_monitor

__all__ = [
    # Signature-based attribution (cooperative case)
    "ActionAttestationService",
    "ActionAttestation",
    "ForensicVerifier",
    "AttributionProof",
    "AttributionConfidence",
    "UnknownSource",
    # Gap-based detection (non-cooperative case)
    "GapDetector",
    "GapReport",
    "Gap",
    "GapKind",
    "ObservedEvent",
    "ObligatedRange",
    "synthesise_events",
    # Range registry: audit and signed append-only chain
    "Confidence",
    "RangeEntry",
    "RegistryAudit",
    "SignedRegistry",
    "SignedEntry",
    "ChainVerdict",
    "audit_registries",
    "load_published_ranges",
    "load_bundled_openai_registries",
    "verify_chain",
    # Key custody boundary
    "CustodyAssurance",
    "CustodyReport",
    "SigningBackend",
    "InProcessSigningBackend",
    "ExternalSigningBackend",
    "pkcs11_backend_stub",
    # Composition analysis
    "ComposabilityDetector",
    "DecompositionAttack",
    "ViolationType",
    "SecurityState",
    # Policy calibration
    "CalibrationReport",
    "Observation",
    "calibrate_policy",
    "measure_holdout_false_positives",
    "synthetic_benign_corpus",
    # Integration
    "VEAMonitor",
    "VEAConfig",
    "create_vea_monitor",
]
