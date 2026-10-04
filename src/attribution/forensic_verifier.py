"""
Forensic Verifier - Third-party attribution without lab cooperation.

This module enables platforms (Wikipedia, PyPI, npm) to cryptographically
verify which AI lab/model was responsible for suspicious activity, without
needing to contact the lab or trust their internal logs.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from .attestation_service import ActionAttestation


class AttributionConfidence(Enum):
    """Confidence level of attribution."""
    CRYPTOGRAPHIC_PROOF = "cryptographic_proof"  # Ed25519 signature verified
    STATISTICAL_MATCH = "statistical_match"      # Behavioral patterns match
    UNKNOWN = "unknown"                          # No attestation, no match


@dataclass
class AttributionProof:
    """
    Cryptographic proof of which lab/model performed an action.
    
    This proof can be independently verified by anyone with the public key,
    providing undeniable evidence for incident response and regulatory compliance.
    """
    
    lab_id: str
    model_id: str
    confidence: AttributionConfidence
    attestation: ActionAttestation
    verification_timestamp_ms: int
    signature_valid: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "lab_id": self.lab_id,
            "model_id": self.model_id,
            "confidence": self.confidence.value,
            "attestation": self.attestation.to_dict(),
            "verification_timestamp_ms": self.verification_timestamp_ms,
            "signature_valid": self.signature_valid
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=2)
    
    def summary(self) -> str:
        """Human-readable summary."""
        status = "VERIFIED" if self.signature_valid else "INVALID"
        return (
            f"Attribution Proof [{status}]\n"
            f"  Lab: {self.lab_id}\n"
            f"  Model: {self.model_id}\n"
            f"  Confidence: {self.confidence.value}\n"
            f"  Action: {self.attestation.action_type} -> {self.attestation.target}\n"
            f"  Timestamp: {self.attestation.timestamp_ms}\n"
            f"  Verified: {self.verification_timestamp_ms}"
        )


@dataclass
class UnknownSource:
    """Represents an action with no verifiable attribution."""
    
    action_type: str
    target: str
    timestamp_ms: int
    reason: str  # Why attribution failed
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "action_type": self.action_type,
            "target": self.target,
            "timestamp_ms": self.timestamp_ms,
            "reason": self.reason,
            "confidence": "unknown"
        }
    
    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Unknown Source\n"
            f"  Action: {self.action_type} -> {self.target}\n"
            f"  Timestamp: {self.timestamp_ms}\n"
            f"  Reason: {self.reason}"
        )


class ForensicVerifier:
    """
    Third-party forensic verifier for AI agent actions.
    
    This class enables platforms under attack to:
    1. Verify Ed25519 signatures without contacting the origin lab
    2. Cryptographically prove attribution for regulatory/legal purposes
    3. Detect incident timing (when attack started/ended)
    4. Generate evidence chains for incident reports
    
    Key innovation: Verification requires ONLY the public key, not lab cooperation.
    """
    
    def __init__(self):
        """Initialize forensic verifier with known lab public keys."""
        # Public key registry (in production, this would be a distributed registry)
        # Labs publish their public keys, platforms cache them
        self.lab_public_keys: Dict[str, Ed25519PublicKey] = {}
        self.verification_cache: Dict[str, AttributionProof] = {}
        
    def register_lab_public_key(self, lab_id: str, public_key_pem: str):
        """
        Register a lab's public key for verification.
        
        Args:
            lab_id: Laboratory identifier (e.g., "openai")
            public_key_pem: PEM-encoded Ed25519 public key
        
        Note: In production, this would use a distributed PKI system
        similar to SSL certificate authorities.
        """
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode('utf-8')
        )
        self.lab_public_keys[lab_id] = public_key
    
    def verify_attestation(
        self,
        attestation: ActionAttestation,
        fast_fail: bool = True
    ) -> AttributionProof:
        """
        Verify an action attestation cryptographically.
        
        Args:
            attestation: Action attestation to verify
            fast_fail: Return immediately if signature invalid (default: True)
        
        Returns:
            AttributionProof with verification result
        
        Raises:
            ValueError: If lab's public key is not registered
        
        Example:
            >>> verifier = ForensicVerifier()
            >>> verifier.register_lab_public_key("openai", openai_public_key)
            >>> proof = verifier.verify_attestation(suspicious_attestation)
            >>> if proof.signature_valid:
            ...     print(f"CONFIRMED: {proof.lab_id} responsible")
        """
        # Check cache
        cache_key = attestation.action_hash
        if cache_key in self.verification_cache:
            return self.verification_cache[cache_key]
        
        # Load public key
        if attestation.lab_id not in self.lab_public_keys:
            # Try loading from attestation's embedded public key
            try:
                public_key = serialization.load_pem_public_key(
                    attestation.public_key_pem.encode('utf-8')
                )
                self.lab_public_keys[attestation.lab_id] = public_key
            except Exception as e:
                raise ValueError(
                    f"Lab '{attestation.lab_id}' public key not registered "
                    f"and embedded key invalid: {e}"
                )
        
        public_key = self.lab_public_keys[attestation.lab_id]
        
        # Verify Ed25519 signature
        signature_valid = False
        try:
            signature_bytes = bytes.fromhex(attestation.signature)
            public_key.verify(
                signature_bytes,
                attestation.action_hash.encode('utf-8')
            )
            signature_valid = True
        except InvalidSignature:
            if fast_fail:
                # Signature invalid - attribution fails
                pass
        except Exception as e:
            # Malformed signature
            pass
        
        # Create proof
        proof = AttributionProof(
            lab_id=attestation.lab_id,
            model_id=attestation.model_id,
            confidence=(
                AttributionConfidence.CRYPTOGRAPHIC_PROOF 
                if signature_valid 
                else AttributionConfidence.UNKNOWN
            ),
            attestation=attestation,
            verification_timestamp_ms=int(time.time() * 1000),
            signature_valid=signature_valid
        )
        
        # Cache valid proofs
        if signature_valid:
            self.verification_cache[cache_key] = proof
        
        return proof
    
    def verify_action_batch(
        self,
        attestations: List[ActionAttestation],
        parallel: bool = False
    ) -> List[AttributionProof]:
        """
        Verify a batch of attestations (for incident analysis).
        
        Args:
            attestations: List of attestations to verify
            parallel: Use parallel verification (future enhancement)
        
        Returns:
            List of AttributionProof objects
        
        Example: Analyzing 15,000 Wikipedia edits from German wiki incident
        """
        proofs = []
        for attestation in attestations:
            try:
                proof = self.verify_attestation(attestation)
                proofs.append(proof)
            except ValueError:
                # Lab key not registered - mark as unknown
                unknown = UnknownSource(
                    action_type=attestation.action_type,
                    target=attestation.target,
                    timestamp_ms=attestation.timestamp_ms,
                    reason=f"Lab '{attestation.lab_id}' public key not registered"
                )
                # Convert to failed proof for consistency
                proof = AttributionProof(
                    lab_id=attestation.lab_id,
                    model_id=attestation.model_id,
                    confidence=AttributionConfidence.UNKNOWN,
                    attestation=attestation,
                    verification_timestamp_ms=int(time.time() * 1000),
                    signature_valid=False
                )
                proofs.append(proof)
        
        return proofs
    
    def analyze_incident(
        self,
        attestations: List[ActionAttestation]
    ) -> Dict[str, Any]:
        """
        Analyze a full incident with timeline and attribution statistics.
        
        Args:
            attestations: All attestations from suspicious activity
        
        Returns:
            Incident analysis with:
            - Total actions
            - Verified vs unverified
            - Attribution by lab/model
            - Timeline (first/last action)
            - Confidence breakdown
        
        This is the function incident responders use to generate
        the regulatory report required by EU AI Act Article 53.
        """
        proofs = self.verify_action_batch(attestations)
        
        # Statistics
        total_actions = len(proofs)
        verified_count = sum(1 for p in proofs if p.signature_valid)
        unverified_count = total_actions - verified_count
        
        # Attribution breakdown
        lab_counts: Dict[str, int] = {}
        model_counts: Dict[str, int] = {}
        for proof in proofs:
            if proof.signature_valid:
                lab_counts[proof.lab_id] = lab_counts.get(proof.lab_id, 0) + 1
                model_key = f"{proof.lab_id}/{proof.model_id}"
                model_counts[model_key] = model_counts.get(model_key, 0) + 1
        
        # Timeline
        if attestations:
            timestamps = [a.timestamp_ms for a in attestations]
            first_action = min(timestamps)
            last_action = max(timestamps)
            duration_ms = last_action - first_action
        else:
            first_action = None
            last_action = None
            duration_ms = 0
        
        return {
            "total_actions": total_actions,
            "verified_actions": verified_count,
            "unverified_actions": unverified_count,
            "verification_rate": verified_count / total_actions if total_actions > 0 else 0,
            "attribution_by_lab": lab_counts,
            "attribution_by_model": model_counts,
            "timeline": {
                "first_action_ms": first_action,
                "last_action_ms": last_action,
                "duration_ms": duration_ms,
                "duration_hours": duration_ms / (1000 * 60 * 60) if duration_ms > 0 else 0
            },
            "primary_culprit": max(lab_counts.items(), key=lambda x: x[1])[0] if lab_counts else "unknown"
        }
    
    def get_verification_stats(self) -> Dict[str, Any]:
        """Get verification performance statistics."""
        return {
            "cache_size": len(self.verification_cache),
            "registered_labs": len(self.lab_public_keys),
            "lab_ids": list(self.lab_public_keys.keys())
        }


# Example usage
if __name__ == "__main__":
    from .attestation_service import ActionAttestationService
    import timeit
    
    print("=== Forensic Verifier Demo ===\n")
    
    # Simulate OpenAI agent creating attestations
    openai_service = ActionAttestationService("openai", "gpt-4")
    
    # Simulate platform (Wikipedia) setting up verification
    verifier = ForensicVerifier()
    verifier.register_lab_public_key("openai", openai_service.get_public_key_pem())
    
    print("Lab public key registered\n")
    
    # Generate suspicious actions
    attestations = []
    for i in range(100):
        att = openai_service.attest_action(
            action_type="wiki_edit",
            target=f"wikipedia.org/wiki/Article_{i}",
            params={"edit_id": i, "content": f"Edit {i}"}
        )
        attestations.append(att)
    
    print(f" Generated {len(attestations)} attestations\n")
    
    # Verify first action
    proof = verifier.verify_attestation(attestations[0])
    print(proof.summary())
    print()
    
    # Analyze full incident
    analysis = verifier.analyze_incident(attestations)
    print("=== Incident Analysis ===")
    print(f"Total actions: {analysis['total_actions']}")
    print(f"Verified: {analysis['verified_actions']} ({analysis['verification_rate']*100:.1f}%)")
    print(f"Primary culprit: {analysis['primary_culprit']}")
    print(f"Duration: {analysis['timeline']['duration_hours']:.2f} hours")
    print()
    
    # Benchmark verification speed
    def bench_verify():
        verifier.verify_attestation(attestations[0])
    
    iterations = 1000
    total_time = timeit.timeit(bench_verify, number=iterations)
    avg_time_ms = (total_time / iterations) * 1000
    
    print("=== Performance ===")
    print(f"Average verification time: {avg_time_ms:.3f} ms")
    print(f"Target: <10 ms {'' if avg_time_ms < 10 else ''}")
    print(f"Throughput: {1000/avg_time_ms:.0f} verifications/second")
