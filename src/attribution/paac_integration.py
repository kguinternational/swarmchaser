"""
PAAC Integration Layer for VEA Attribution System

Connects VEA cryptographic attribution with PAAC's existing monitoring infrastructure.
Enables automatic attestation generation for all code modifications and real-time
composition violation detection.
"""

import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .attestation_service import ActionAttestationService, ActionAttestation
from .forensic_verifier import ForensicVerifier
from .composability_detector import ComposabilityDetector, DecompositionAttack


@dataclass
class VEAConfig:
    """Configuration for VEA integration with PAAC."""
    
    enabled: bool = True
    lab_id: str = "unknown"
    model_id: str = "unknown"
    private_key_pem: Optional[str] = None  # If None, generates ephemeral key
    auto_attest: bool = True  # Automatically attest all modifications
    detect_composition: bool = True  # Enable composability detection
    max_sequence_length: int = 100  # Max actions to track for composition
    audit_log_path: str = "vea_audit.jsonl"


class VEAMonitor:
    """
    VEA-enabled monitor that wraps PAAC's code monitoring with attribution.
    
    Features:
    1. Automatic attestation generation for every code modification
    2. Real-time composition violation detection
    3. Audit trail with cryptographic proofs
    4. Integration with existing PAAC verification pipeline
    
    Example integration:
        # In PAAC's code_monitor.py __init__:
        vea_config = VEAConfig(
            lab_id="openai",
            model_id="gpt-4",
            enabled=config.get("vea_enabled", False)
        )
        self.vea_monitor = VEAMonitor(vea_config) if vea_config.enabled else None
        
        # In propose_modification():
        if self.vea_monitor:
            attestation = self.vea_monitor.attest_modification(modification)
            # Check for composition violations
            attack = self.vea_monitor.check_composition_violation(attestation)
            if attack:
                raise SecurityError(f"Decomposition attack detected: {attack}")
    """
    
    def __init__(self, config: VEAConfig):
        """
        Initialize VEA monitor.
        
        Args:
            config: VEA configuration
        """
        self.config = config
        
        if not config.enabled:
            return
        
        # Initialize attestation service
        if config.private_key_pem:
            private_key = ActionAttestationService.load_private_key_from_pem(
                config.private_key_pem
            )
            self.attestation_service = ActionAttestationService(
                lab_id=config.lab_id,
                model_id=config.model_id,
                private_key=private_key
            )
        else:
            self.attestation_service = ActionAttestationService(
                lab_id=config.lab_id,
                model_id=config.model_id
            )
        
        # Initialize forensic verifier for self-verification
        self.verifier = ForensicVerifier()
        self.verifier.register_lab_public_key(
            config.lab_id,
            self.attestation_service.get_public_key_pem()
        )
        
        # Initialize composability detector
        self.detector = ComposabilityDetector(self.verifier)
        
        # Track recent attestations for composition analysis
        self.recent_attestations: List[ActionAttestation] = []
        
        # Audit log
        self.audit_log_path = config.audit_log_path
    
    def attest_modification(
        self,
        func_name: str,
        old_code: str,
        new_code: str,
        agent_id: str = "unknown"
    ) -> Optional[ActionAttestation]:
        """
        Generate cryptographic attestation for a code modification.
        
        Args:
            func_name: Function being modified
            old_code: Previous code
            new_code: New code
            agent_id: Agent identifier
        
        Returns:
            ActionAttestation or None if VEA disabled
        """
        if not self.config.enabled or not self.config.auto_attest:
            return None
        
        # Generate attestation
        attestation = self.attestation_service.attest_action(
            action_type="code_modification",
            target=func_name,
            params={
                "old_hash": self._hash_code(old_code),
                "new_hash": self._hash_code(new_code),
                "agent_id": agent_id,
                "timestamp": int(time.time() * 1000)
            }
        )
        
        # Add to recent attestations for composition tracking
        self.recent_attestations.append(attestation)
        
        # Trim if exceeds max length
        if len(self.recent_attestations) > self.config.max_sequence_length:
            self.recent_attestations = self.recent_attestations[-self.config.max_sequence_length:]
        
        # Audit log
        self._log_attestation(attestation, func_name, agent_id)
        
        return attestation
    
    def check_composition_violation(
        self,
        new_attestation: Optional[ActionAttestation] = None
    ) -> Optional[DecompositionAttack]:
        """
        Check for composition violations in recent action sequence.
        
        Args:
            new_attestation: Newly created attestation (optional, uses recent if None)
        
        Returns:
            DecompositionAttack if violation detected, None otherwise
        """
        if not self.config.enabled or not self.config.detect_composition:
            return None
        
        if not self.recent_attestations:
            return None
        
        # Analyze recent sequence
        attack = self.detector.analyze_action_sequence(self.recent_attestations)
        
        if attack:
            self._log_attack(attack)
        
        return attack
    
    def get_attribution_proof(
        self,
        attestation: ActionAttestation
    ) -> Optional[Dict[str, Any]]:
        """
        Generate attribution proof for an attestation.
        
        Args:
            attestation: Attestation to verify
        
        Returns:
            Attribution proof dictionary or None if verification fails
        """
        if not self.config.enabled:
            return None
        
        proof = self.verifier.verify_attestation(attestation)
        
        return {
            "lab_id": proof.lab_id,
            "model_id": proof.model_id,
            "confidence": proof.confidence.value,
            "signature_valid": proof.signature_valid,
            "action_hash": attestation.action_hash,
            "timestamp": attestation.timestamp_ms,
            "verification_timestamp": proof.verification_timestamp_ms
        }
    
    def export_incident_report(
        self,
        start_time_ms: int,
        end_time_ms: int
    ) -> Dict[str, Any]:
        """
        Export incident report for regulatory compliance.
        
        Generates report compatible with EU AI Act Article 53 requirements.
        
        Args:
            start_time_ms: Incident start time
            end_time_ms: Incident end time
        
        Returns:
            Incident report dictionary
        """
        if not self.config.enabled:
            return {"error": "VEA not enabled"}
        
        # Filter attestations by time range
        incident_attestations = [
            att for att in self.recent_attestations
            if start_time_ms <= att.timestamp_ms <= end_time_ms
        ]
        
        if not incident_attestations:
            return {"error": "No attestations in time range"}
        
        # Generate analysis
        analysis = self.verifier.analyze_incident(incident_attestations)
        
        # Check for composition violations
        attack = self.detector.analyze_action_sequence(incident_attestations)
        
        return {
            "report_type": "ai_agent_incident",
            "standard": "eu_ai_act_article_53",
            "incident_period": {
                "start_ms": start_time_ms,
                "end_ms": end_time_ms,
                "duration_hours": (end_time_ms - start_time_ms) / (1000 * 60 * 60)
            },
            "attribution": {
                "lab_id": analysis["primary_culprit"],
                "model_id": self.config.model_id,
                "confidence": "cryptographic_proof",
                "total_actions": analysis["total_actions"],
                "verified_actions": analysis["verified_actions"],
                "verification_rate": analysis["verification_rate"]
            },
            "composition_violation": {
                "detected": attack is not None,
                "type": attack.violation_type.value if attack else None,
                "sequence_length": len(attack.blamed_sequence) if attack else 0,
                "evidence_available": attack is not None
            },
            "timeline": analysis["timeline"],
            "cryptographic_proofs": len(incident_attestations),
            "report_generated_ms": int(time.time() * 1000)
        }
    
    def _hash_code(self, code: str) -> str:
        """Generate SHA-256 hash of code."""
        import hashlib
        return hashlib.sha256(code.encode('utf-8')).hexdigest()
    
    def _log_attestation(
        self,
        attestation: ActionAttestation,
        func_name: str,
        agent_id: str
    ):
        """Log attestation to audit trail."""
        entry = {
            "type": "attestation",
            "timestamp": int(time.time() * 1000),
            "func_name": func_name,
            "agent_id": agent_id,
            "action_hash": attestation.action_hash,
            "signature": attestation.signature[:32] + "...",  # Truncate for readability
            "lab_id": attestation.lab_id,
            "model_id": attestation.model_id
        }
        
        with open(self.audit_log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    def _log_attack(self, attack: DecompositionAttack):
        """Log detected attack to audit trail."""
        entry = {
            "type": "decomposition_attack",
            "timestamp": int(time.time() * 1000),
            "violation_type": attack.violation_type.value,
            "lab_id": attack.lab_id,
            "model_id": attack.model_id,
            "sequence_length": len(attack.blamed_sequence),
            "composed_violation": attack.composed_violation,
            "detection_timestamp": attack.detection_timestamp_ms
        }
        
        with open(self.audit_log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')


# Helper function for easy PAAC integration
def create_vea_monitor(paac_config: Dict[str, Any]) -> Optional[VEAMonitor]:
    """
    Create VEA monitor from PAAC configuration.
    
    Usage in PAAC's code_monitor.py:
        from src.attribution.paac_integration import create_vea_monitor
        
        self.vea_monitor = create_vea_monitor(config)
        
        # In propose_modification():
        if self.vea_monitor:
            attestation = self.vea_monitor.attest_modification(
                func_name=mod.func_name,
                old_code=mod.old_code,
                new_code=mod.new_code,
                agent_id=mod.agent_id
            )
    
    Args:
        paac_config: PAAC configuration dictionary
    
    Returns:
        VEAMonitor instance or None if VEA disabled
    """
    vea_enabled = paac_config.get("vea_enabled", False)
    
    if not vea_enabled:
        return None
    
    vea_config = VEAConfig(
        enabled=True,
        lab_id=paac_config.get("vea_lab_id", "unknown"),
        model_id=paac_config.get("vea_model_id", "unknown"),
        private_key_pem=paac_config.get("vea_private_key_pem"),
        auto_attest=paac_config.get("vea_auto_attest", True),
        detect_composition=paac_config.get("vea_detect_composition", True),
        max_sequence_length=paac_config.get("vea_max_sequence_length", 100),
        audit_log_path=paac_config.get("vea_audit_log", "vea_audit.jsonl")
    )
    
    return VEAMonitor(vea_config)


# Example integration snippet for PAAC
INTEGRATION_EXAMPLE = '''
# In src/monitor/code_monitor.py

from src.attribution.paac_integration import create_vea_monitor

class CodeMonitor:
    def __init__(self, config: dict[str, Any]):
        # ... existing initialization ...
        
        # Add VEA integration
        self.vea_monitor = create_vea_monitor(config)
    
    def propose_modification(self, mod: CodeModification) -> tuple[bool, str]:
        # Generate attestation BEFORE verification
        if self.vea_monitor:
            attestation = self.vea_monitor.attest_modification(
                func_name=mod.func_name,
                old_code=mod.old_code,
                new_code=mod.new_code,
                agent_id=mod.agent_id
            )
            
            # Check for composition violations
            attack = self.vea_monitor.check_composition_violation(attestation)
            if attack:
                _audit_logger.warning(
                    f"Decomposition attack detected: {attack.violation_type.value}"
                )
                return False, f"Composition violation: {attack.composed_violation}"
        
        # ... existing verification logic ...
        
        # If verification passes and attestation exists, log success
        if self.vea_monitor and attestation:
            proof = self.vea_monitor.get_attribution_proof(attestation)
            _audit_logger.info(f"Modification attested: {proof}")
        
        return True, "UNSAT"
'''


if __name__ == "__main__":
    print("VEA-PAAC Integration Example")
    print("=" * 70)
    print(INTEGRATION_EXAMPLE)
    print("=" * 70)
    
    # Demonstration
    print("\nDemonstration:\n")
    
    config = VEAConfig(
        enabled=True,
        lab_id="demo_lab",
        model_id="demo_model"
    )
    
    monitor = VEAMonitor(config)
    
    print(" VEA Monitor initialized")
    print(f"  Lab: {config.lab_id}")
    print(f"  Model: {config.model_id}")
    print(f"  Auto-attest: {config.auto_attest}")
    print(f"  Detect composition: {config.detect_composition}")
    
    # Simulate modifications
    print("\n Simulating code modifications...")
    
    for i in range(5):
        attestation = monitor.attest_modification(
            func_name=f"function_{i}",
            old_code=f"def function_{i}(): pass",
            new_code=f"def function_{i}(): return {i}",
            agent_id="demo_agent"
        )
        print(f"  Modification {i+1}: Attested ({attestation.action_hash[:16]}...)")
    
    # Check composition
    print("\n Checking for composition violations...")
    attack = monitor.check_composition_violation()
    
    if attack:
        print(f"   Attack detected: {attack.violation_type.value}")
    else:
        print("   No composition violations detected")
    
    # Export report
    print("\n Generating incident report...")
    report = monitor.export_incident_report(
        start_time_ms=int((time.time() - 60) * 1000),
        end_time_ms=int(time.time() * 1000)
    )
    
    print(f"  Total actions: {report['attribution']['total_actions']}")
    print(f"  Verified: {report['attribution']['verified_actions']}")
    print(f"  Attribution: {report['attribution']['lab_id']}")
    print(f"  Cryptographic proofs: {report['cryptographic_proofs']}")
