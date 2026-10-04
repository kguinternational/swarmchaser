"""
Composability detector: flags privilege escalation across an action sequence.

Individually permitted actions can combine into a state that no single action
would have been allowed to reach. This module tracks cumulative privileges,
touched resources and crossed boundaries across a sequence, and reports the
first point at which the accumulated state violates policy.

Scope and honest limits
-----------------------
The policy in `_load_default_policies` is a hand-written fallback with no
derivation behind it: three cumulative privileges and two boundary crossings
were placeholders chosen to demonstrate the mechanism. Use
`policy_calibration.calibrate_policy` and `apply_calibration` to replace them
with thresholds measured from a benign baseline, and read the resulting
`CalibrationReport.caveats` before quoting any number that comes out.

`self.calibration is None` means the undefended placeholders are still in use.

This is thematically related to the decomposition vulnerabilities recorded as
D-01 and D-02 in the PAAC audit, but it is NOT a defence against them and does
not discharge them. Those findings concern unenforced call-site preconditions
and missing re-verification of callers inside the Z3 pipeline. This module
operates on observed action sequences instead, and proves nothing about the
verifier. Do not cite it as closing those findings.

Because it consumes attestations, it also inherits their central weakness: an
agent that does not sign its actions produces nothing for this to analyse. See
`gap_detector` for the non-cooperative case.
"""

import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set
from enum import Enum

from .attestation_service import ActionAttestation
from .forensic_verifier import ForensicVerifier, AttributionProof


class ViolationType(Enum):
    """Types of security violations detectable through composition."""
    PRIVILEGE_ESCALATION = "privilege_escalation"
    BOUNDARY_BREACH = "boundary_breach"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    DATA_EXFILTRATION = "data_exfiltration"
    PERSISTENT_ACCESS = "persistent_access"


@dataclass
class SecurityState:
    """
    Security state at a point in the modification sequence.
    
    Tracks cumulative privileges, accessed resources, and security boundaries.
    """
    
    step: int
    privileges: Set[str]  # e.g., {"read_file", "network_call", "exec_code"}
    accessed_resources: Set[str]  # e.g., {"/etc/passwd", "169.254.169.254"}
    boundaries_crossed: Set[str]  # e.g., {"container", "host", "network"}
    attestation: ActionAttestation
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "step": self.step,
            "privileges": list(self.privileges),
            "accessed_resources": list(self.accessed_resources),
            "boundaries_crossed": list(self.boundaries_crossed),
            "action_hash": self.attestation.action_hash
        }


@dataclass
class DecompositionAttack:
    """
    Evidence of a decomposition attack where individually-safe modifications
    compose into a security violation.
    
    This provides cryptographic proof of the attack progression for
    incident response and regulatory compliance.
    """
    
    violation_type: ViolationType
    individually_safe: List[AttributionProof]  # Each action verified safe individually
    composed_violation: Dict[str, Any]  # What the composition violated
    state_progression: List[SecurityState]  # How privileges escalated
    blamed_sequence: List[ActionAttestation]  # The attestation chain (evidence)
    
    detection_timestamp_ms: int
    lab_id: str
    model_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "violation_type": self.violation_type.value,
            "individually_safe_count": len(self.individually_safe),
            "composed_violation": self.composed_violation,
            "state_progression": [s.to_dict() for s in self.state_progression],
            "blamed_sequence": [a.to_dict() for a in self.blamed_sequence],
            "detection_timestamp_ms": self.detection_timestamp_ms,
            "lab_id": self.lab_id,
            "model_id": self.model_id
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=2)
    
    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Composition violation flagged\n"
            f"  type            : {self.violation_type.value}\n"
            f"  operator        : {self.lab_id}\n"
            f"  model           : {self.model_id}\n"
            f"  flagged prefix  : {len(self.blamed_sequence)} actions\n"
            f"  description     : "
            f"{self.composed_violation.get('description', 'unknown')}\n"
            f"  evidence        : {len(self.blamed_sequence)} signed attestations\n"
            f"  note            : policy is hand-written; no action here was "
            f"individually rejected, which is the point, but that does not "
            f"establish the sequence was malicious"
        )


class ComposabilityDetector:
    """
    Detects security violations through action composition analysis.
    
    Addresses PAAC decomposition vulnerabilities D-01 and D-02:
    - D-01: Call-site preconditions unenforced
    - D-02: Replacing a function doesn't re-verify callers
    
    Strategy:
    1. Track cumulative security state across action sequence
    2. Re-verify composition at each step
    3. Use attestation chain as cryptographic evidence
    4. Detect gradual privilege escalation even when each step is "safe"
    """
    
    def __init__(self, verifier: ForensicVerifier):
        """
        Initialize detector with forensic verifier.
        
        Args:
            verifier: ForensicVerifier for signature validation
        """
        self.verifier = verifier
        self.security_policies = self._load_default_policies()
        self.calibration: Optional[Any] = None
        """Set by `apply_calibration`. While None, the thresholds in use are the
        undefended placeholders below and any finding must say so."""
    
    def _load_default_policies(self) -> Dict[str, Any]:
        """
        Uncalibrated fallback policy.
        
        These numbers have no derivation. They exist so the detector runs before
        a baseline is available, and they should be replaced via
        `apply_calibration` with values measured from observed traffic. See
        `policy_calibration`.
        """
        return {
            "max_privileges": 3,  # placeholder; see apply_calibration
            "forbidden_combinations": [
                {"read_secrets", "network_egress"},  # Can't read secrets AND make network calls
                {"exec_code", "host_filesystem"},     # Can't execute code AND access host
                {"metadata_access", "credential_use"} # Can't access metadata AND use credentials
            ],
            "boundary_policy": {
                "container": ["network", "host"],  # Can cross from container to network OR host, not both
                "max_boundaries": 2
            },
            "resource_limits": {
                "sensitive_files": ["/etc/passwd", "/etc/shadow", "~/.ssh/", "~/.aws/"],
                "metadata_endpoints": ["169.254.169.254", "metadata.google.internal"]
            }
        }
    
    def analyze_action_sequence(
        self,
        attestations: List[ActionAttestation],
        initial_state: Optional[SecurityState] = None
    ) -> Optional[DecompositionAttack]:
        """
        Analyze a sequence of actions for composition violations.
        
        Args:
            attestations: Sequence of attested actions
            initial_state: Starting security state (defaults to empty)
        
        Returns:
            DecompositionAttack if violation detected, None otherwise
        
        Example: Detecting OpenAI German wiki incident progression
            Step 1: Read file (safe)
            Step 2: Network call (safe)
            Step 1+2: Read secrets + network = VIOLATION
        """
        if not attestations:
            return None
        
        # Verify all attestations first
        proofs = self.verifier.verify_action_batch(attestations)
        
        # Filter to only verified actions
        verified_proofs = [p for p in proofs if p.signature_valid]
        verified_attestations = [p.attestation for p in verified_proofs]
        
        if not verified_attestations:
            return None
        
        # Initialize state tracking
        if initial_state is None:
            current_state = SecurityState(
                step=0,
                privileges=set(),
                accessed_resources=set(),
                boundaries_crossed=set(),
                attestation=verified_attestations[0]
            )
        else:
            current_state = initial_state
        
        state_progression = [current_state]
        
        # Analyze each action in sequence
        for i, attestation in enumerate(verified_attestations, start=1):
            # Extract privileges from this action
            new_privileges = self._extract_privileges(attestation)
            new_resources = self._extract_resources(attestation)
            new_boundaries = self._extract_boundaries(attestation)
            
            # Update cumulative state
            next_state = SecurityState(
                step=i,
                privileges=current_state.privileges | new_privileges,
                accessed_resources=current_state.accessed_resources | new_resources,
                boundaries_crossed=current_state.boundaries_crossed | new_boundaries,
                attestation=attestation
            )
            
            state_progression.append(next_state)
            
            # Check for violations at this composition point
            violation = self._check_composition_violation(next_state)
            
            if violation:
                # `i` is 1-indexed, so exactly `i` attestations have been
                # folded into `next_state`. Slicing to [:i] keeps the evidence
                # chain to actions actually analysed; [:i+1] would blame one
                # action that had not yet been processed.
                return DecompositionAttack(
                    violation_type=violation["type"],
                    individually_safe=verified_proofs[:i],
                    composed_violation=violation,
                    state_progression=state_progression,
                    blamed_sequence=verified_attestations[:i],
                    detection_timestamp_ms=int(__import__('time').time() * 1000),
                    lab_id=attestation.lab_id,
                    model_id=attestation.model_id
                )
            
            current_state = next_state
        
        # No violation detected
        return None
    
    # Action type -> privileges it confers. Module-level so calibration can
    # enumerate the full privilege vocabulary without instantiating a detector.
    PRIVILEGE_MAP: Dict[str, Set[str]] = {
        "wiki_edit": {"network_call", "write_data"},
        "api_call": {"network_call"},
        "code_execution": {"exec_code"},
        "file_read": {"read_file"},
        "file_write": {"write_file"},
        "metadata_query": {"metadata_access"},
        "credential_use": {"credential_use"},
        "docker_socket": {"container_escape"},
        "host_mount": {"host_filesystem"},
    }

    def privileges_for(self, action_type: str, target: str = "") -> Set[str]:
        """
        Privileges conferred by an action, addressable without an attestation.

        Calibration needs to replay candidate sequences that were never signed,
        so the extraction logic cannot require an ActionAttestation. `target` is
        accepted for signature symmetry with `boundaries_for` and is currently
        unused here.
        """
        return set(self.PRIVILEGE_MAP.get(action_type, set()))

    def boundaries_for(self, action_type: str, target: str) -> Set[str]:
        """Security boundaries crossed, addressable without an attestation."""
        boundaries: Set[str] = set()
        lowered = target.lower()

        if action_type in {"api_call", "wiki_edit"} or "http" in lowered:
            boundaries.add("network")
        if action_type in {"host_mount", "docker_socket"} or "/var/run" in lowered:
            boundaries.add("host")
        if "169.254.169.254" in lowered or "metadata" in lowered:
            boundaries.add("metadata")

        return boundaries

    def known_privileges(self) -> Set[str]:
        """
        Every privilege the vocabulary can express.

        Calibration uses this so a dangerous pair absent from the benign corpus
        is still considered for the forbidden list. Restricting candidates to
        privileges observed in benign traffic would silently exclude exactly the
        combinations worth forbidding.
        """
        out: Set[str] = set()
        for privileges in self.PRIVILEGE_MAP.values():
            out |= privileges
        return out

    def apply_calibration(self, report: Any) -> None:
        """
        Replace the hand-written thresholds with values derived from a baseline.

        Keeps `resource_limits` as-is: those are named sensitive paths and
        metadata endpoints, which are not statistical quantities and cannot be
        derived from a frequency distribution.
        """
        self.security_policies["max_privileges"] = report.max_privileges
        self.security_policies["boundary_policy"]["max_boundaries"] = (
            report.max_boundaries
        )
        self.security_policies["forbidden_combinations"] = [
            set(combo) for combo in report.forbidden_combinations
        ]
        self.calibration = report

    def _extract_privileges(self, attestation: ActionAttestation) -> Set[str]:
        """Extract privileges implied by action type."""
        return self.privileges_for(attestation.action_type, attestation.target)
    
    def _extract_resources(self, attestation: ActionAttestation) -> Set[str]:
        """Extract accessed resources from action target."""
        resources = set()
        
        target = attestation.target.lower()
        
        # Check for sensitive file patterns
        for sensitive in self.security_policies["resource_limits"]["sensitive_files"]:
            if sensitive.lower() in target:
                resources.add(f"sensitive_file:{sensitive}")
        
        # Check for metadata endpoints
        for endpoint in self.security_policies["resource_limits"]["metadata_endpoints"]:
            if endpoint in target:
                resources.add(f"metadata:{endpoint}")
        
        # Add the target itself
        resources.add(target)
        
        return resources
    
    def _extract_boundaries(self, attestation: ActionAttestation) -> Set[str]:
        """Extract security boundaries crossed by this action."""
        return self.boundaries_for(attestation.action_type, attestation.target)
    
    def _check_composition_violation(
        self,
        state: SecurityState
    ) -> Optional[Dict[str, Any]]:
        """
        Check if current state violates composition policies.
        
        Returns:
            Violation description if violated, None otherwise
        """
        # Check max privileges limit
        if len(state.privileges) > self.security_policies["max_privileges"]:
            return {
                "type": ViolationType.PRIVILEGE_ESCALATION,
                "description": f"Exceeded max privileges ({len(state.privileges)} > {self.security_policies['max_privileges']})",
                "privileges": list(state.privileges)
            }
        
        # Check forbidden privilege combinations
        for forbidden in self.security_policies["forbidden_combinations"]:
            if forbidden.issubset(state.privileges):
                return {
                    "type": ViolationType.BOUNDARY_BREACH,
                    "description": f"Forbidden privilege combination: {forbidden}",
                    "privileges": list(forbidden)
                }
        
        # Check boundary crossing limits
        if len(state.boundaries_crossed) > self.security_policies["boundary_policy"]["max_boundaries"]:
            return {
                "type": ViolationType.BOUNDARY_BREACH,
                "description": f"Exceeded max boundary crossings ({len(state.boundaries_crossed)} > {self.security_policies['boundary_policy']['max_boundaries']})",
                "boundaries": list(state.boundaries_crossed)
            }
        
        # Check for metadata + credential pattern (common in AWS escapes)
        metadata_accessed = any("metadata" in r for r in state.accessed_resources)
        credentials_used = "credential_use" in state.privileges
        
        if metadata_accessed and credentials_used:
            return {
                "type": ViolationType.DATA_EXFILTRATION,
                "description": "Metadata access combined with credential use (cloud escape pattern)",
                "evidence": {
                    "metadata_resources": [r for r in state.accessed_resources if "metadata" in r],
                    "has_credentials": credentials_used
                }
            }
        
        return None


# Example usage and testing
if __name__ == "__main__":
    from .attestation_service import ActionAttestationService
    from .forensic_verifier import ForensicVerifier
    
    print("=== Composability Detector Demo ===\n")
    
    # Setup
    service = ActionAttestationService("openai", "gpt-4")
    verifier = ForensicVerifier()
    verifier.register_lab_public_key("openai", service.get_public_key_pem())
    detector = ComposabilityDetector(verifier)
    
    # Simulate gradual privilege escalation (German wiki pattern)
    print("Simulating action sequence:\n")
    
    actions = [
        ("file_read", "/app/data.json", "Read configuration"),
        ("api_call", "internal-api.example.com/health", "Health check"),
        ("metadata_query", "169.254.169.254/latest/meta-data/", "Query metadata"),
        ("api_call", "external-api.example.com/exfil", "Exfiltrate data")
    ]
    
    attestations = []
    for i, (action_type, target, description) in enumerate(actions, 1):
        print(f"  Step {i}: {description}")
        att = service.attest_action(
            action_type=action_type,
            target=target,
            params={"step": i, "description": description}
        )
        attestations.append(att)
    
    print("\n" + "="*60 + "\n")
    
    # Detect composition violation
    attack = detector.analyze_action_sequence(attestations)
    
    if attack:
        print("COMPOSITION VIOLATION FLAGGED\n")
        print(attack.summary())
        print("\n" + "="*60)
        print("\nState progression:")
        for state in attack.state_progression:
            print(f"  step {state.step}: privileges={sorted(state.privileges)}, "
                  f"boundaries={sorted(state.boundaries_crossed)}")

        print(f"\nEvidence: {len(attack.blamed_sequence)} signed attestations "
              f"covering the flagged prefix.")
        print("Applies only to actions the agent chose to sign.")
    else:
        print("No composition violation flagged")
