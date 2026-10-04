"""
Action Attestation Service - Core Ed25519 signing for agent actions.

This module provides cryptographic attestation for every AI agent action,
enabling third-party verification and forensic attribution without requiring
access to the originating lab's internal systems.
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey
)
from cryptography.hazmat.primitives import serialization


@dataclass
class ActionAttestation:
    """Cryptographically signed attestation of an AI agent action."""
    
    action_hash: str
    signature: str  # base64-encoded Ed25519 signature
    lab_id: str  # e.g., "openai", "anthropic", "deepmind"
    model_id: str  # e.g., "gpt-4", "claude-3.5-sonnet"
    timestamp_ms: int
    public_key_pem: str
    action_type: str  # e.g., "wiki_edit", "api_call", "code_execution"
    target: str  # e.g., "wikipedia.org/wiki/AI_safety"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), sort_keys=True)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionAttestation':
        """Deserialize from dictionary."""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ActionAttestation':
        """Deserialize from JSON."""
        return cls.from_dict(json.loads(json_str))


class ActionAttestationService:
    """
    Generates Ed25519 attestations for agent actions.
    
    Each action receives a cryptographic signature that:
    1. Proves which lab/model generated it
    2. Cannot be forged without the private key
    3. Can be verified by third parties using only the public key
    
    This enables instant attribution during incident response.
    """
    
    def __init__(
        self,
        lab_id: str,
        model_id: str,
        private_key: Optional[Ed25519PrivateKey] = None,
        signing_backend: Optional[Any] = None
    ):
        """
        Initialize attestation service.
        
        Args:
            lab_id: Laboratory identifier (e.g., "openai")
            model_id: Model identifier (e.g., "gpt-4")
            private_key: Ed25519 private key (generates ephemeral if None).
                Ignored when signing_backend is supplied.
            signing_backend: A key_custody.SigningBackend. When supplied, this
                service never holds key material and signing crosses whatever
                custody boundary the backend implements. When omitted, an
                in-process software key is used, which reports IN_PROCESS
                custody and is not adequate for attestations intended as
                evidence. See key_custody for why that distinction matters.
        """
        self.lab_id = lab_id
        self.model_id = model_id
        
        if signing_backend is None:
            # Local import: keeps key_custody optional for callers that only
            # verify, and avoids a cycle if custody ever needs attestation types.
            from .key_custody import InProcessSigningBackend
            signing_backend = InProcessSigningBackend(private_key)
        
        self.signing_backend = signing_backend
        self.public_key_pem = signing_backend.public_key_pem()
    
    @property
    def custody_assurance(self):
        """
        Custody level of the signing key backing every attestation issued here.
        
        Surfaced on the service because a verifier needs it to weigh the
        attestation, and because leaving it buried in the backend invites
        treating an in-process demo key as if it constrained the operator.
        """
        return self.signing_backend.custody_assurance
    
    def attest_action(
        self,
        action_type: str,
        target: str,
        params: Dict[str, Any]
    ) -> ActionAttestation:
        """
        Generate cryptographic attestation for an agent action.
        
        Args:
            action_type: Type of action (e.g., "wiki_edit", "api_call")
            target: Target system/resource
            params: Action parameters (will be hashed into signature)
        
        Returns:
            ActionAttestation with Ed25519 signature
        
        Example:
            >>> service = ActionAttestationService("openai", "gpt-4")
            >>> attestation = service.attest_action(
            ...     action_type="wiki_edit",
            ...     target="wikipedia.org/wiki/AI_safety",
            ...     params={"content": "Updated definition", "section": 2}
            ... )
            >>> # attestation.signature can now be verified by anyone with public_key
        """
        timestamp_ms = int(time.time() * 1000)
        
        # Create canonical representation for hashing
        action_data = {
            "action_type": action_type,
            "target": target,
            "params": params,
            "lab_id": self.lab_id,
            "model_id": self.model_id,
            "timestamp_ms": timestamp_ms
        }
        
        # Hash the action (SHA-256)
        canonical_json = json.dumps(action_data, sort_keys=True)
        action_hash = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
        
        # Sign the hash. Crosses the custody boundary; no key material here.
        signature_bytes = self.signing_backend.sign(action_hash.encode('utf-8'))
        signature_b64 = signature_bytes.hex()
        
        return ActionAttestation(
            action_hash=action_hash,
            signature=signature_b64,
            lab_id=self.lab_id,
            model_id=self.model_id,
            timestamp_ms=timestamp_ms,
            public_key_pem=self.public_key_pem,
            action_type=action_type,
            target=target
        )
    
    def get_public_key_pem(self) -> str:
        """Get PEM-encoded public key for distribution."""
        return self.public_key_pem
    
    @staticmethod
    def load_private_key_from_pem(pem_data: str) -> Ed25519PrivateKey:
        """Load private key from PEM format."""
        return serialization.load_pem_private_key(
            pem_data.encode('utf-8'),
            password=None
        )
    
    @staticmethod
    def load_public_key_from_pem(pem_data: str) -> Ed25519PublicKey:
        """Load public key from PEM format."""
        return serialization.load_pem_public_key(
            pem_data.encode('utf-8')
        )


# Example usage and benchmarking
if __name__ == "__main__":
    import timeit
    
    # Initialize service
    service = ActionAttestationService(
        lab_id="openai",
        model_id="gpt-4"
    )
    
    print(f"Lab: {service.lab_id}")
    print(f"Model: {service.model_id}")
    print(f"Public Key:\n{service.get_public_key_pem()}")
    
    # Generate attestation
    attestation = service.attest_action(
        action_type="wiki_edit",
        target="wikipedia.org/wiki/AI_safety",
        params={
            "content": "Updated definition of AI safety",
            "section": 2,
            "edit_id": "12345"
        }
    )
    
    print(f"\nAttestation:")
    print(f"  Hash: {attestation.action_hash}")
    print(f"  Signature: {attestation.signature[:64]}...")
    print(f"  Timestamp: {attestation.timestamp_ms}")
    
    # Benchmark attestation speed
    def bench_attest():
        service.attest_action(
            "api_call",
            "api.example.com/v1/data",
            {"method": "GET", "path": "/users/123"}
        )
    
    iterations = 1000
    total_time = timeit.timeit(bench_attest, number=iterations)
    avg_time_ms = (total_time / iterations) * 1000
    
    print(f"\nPerformance:")
    print(f"  Iterations: {iterations}")
    print(f"  Average time: {avg_time_ms:.3f} ms")
    print(f"  Under 10 ms target: {'yes' if avg_time_ms < 10 else 'no'}")
