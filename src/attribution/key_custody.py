"""
Signing-key custody boundary.

Why this exists
---------------
`ActionAttestationService` generates an Ed25519 private key in process memory
and holds it for its lifetime. For a demonstration that is fine. For the
mandate the report argues for, it is the weakest point in the whole design: an
attestation is only evidence of origin if the key could not have been used by
anyone other than the operator, and a key sitting in the address space of the
process running the agent does not have that property. An agent that escapes
its sandbox and reads its own process memory can sign whatever it likes, and an
attacker who exfiltrates the key can frame the operator indefinitely.

What this module does
---------------------
It makes custody an explicit, swappable boundary rather than an implicit
assumption. `SigningBackend` is the interface; everything above it never sees
key material. Two implementations ship:

  InProcessSigningBackend   Key in process memory. Honest about being unsuitable
                            for production, and says so through
                            `custody_assurance`.

  ExternalSigningBackend    Delegates to a callable that performs the signature
                            elsewhere: an HSM via PKCS#11, a cloud KMS, or a
                            separate signing daemon. The seam is the point; this
                            repository does not ship an HSM driver and does not
                            pretend to.

What this module does not do
----------------------------
No hardware is involved. `ExternalSigningBackend` is a documented integration
point that has been exercised against a stub, not a validated PKCS#11 binding.
Anyone reading `CustodyAssurance.HARDWARE_BACKED` should treat it as a claim
made by whoever configured the backend, not as something this code verified.
That distinction is the reason the enum exists rather than a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class CustodyAssurance(Enum):
    """
    How much an attestation's origin claim is actually worth.

    This is a property of the deployment, not of the cryptography. Ed25519 is
    equally strong in all three cases; what differs is who could have invoked
    it.
    """

    IN_PROCESS = "in_process"
    """Key in the signing process's memory. An agent with read access to its own
    process, or any code-execution foothold, can sign arbitrarily. Attestations
    are not evidence against the operator's own agent."""

    EXTERNAL_PROCESS = "external_process"
    """Key held by a separate process or daemon. Raises the bar to crossing a
    process boundary, but a compromised host still yields signing capability."""

    HARDWARE_BACKED = "hardware_backed"
    """Key non-exportable, held in an HSM or equivalent. Signing requires an
    authenticated call the device can rate-limit and log. This is the only level
    at which an attestation meaningfully constrains the operator. Asserted by
    configuration; not verified by this code."""

    @property
    def is_production_suitable(self) -> bool:
        """
        Whether a mandate could rest on attestations from this custody level.

        Deliberately strict. If the answer were True for IN_PROCESS, the whole
        argument for attestation as evidence would collapse.
        """
        return self is CustodyAssurance.HARDWARE_BACKED

    @property
    def rationale(self) -> str:
        return {
            CustodyAssurance.IN_PROCESS: (
                "key is readable by the process it protects against"
            ),
            CustodyAssurance.EXTERNAL_PROCESS: (
                "host compromise still grants signing capability"
            ),
            CustodyAssurance.HARDWARE_BACKED: (
                "key non-exportable; signing is an auditable, rate-limitable "
                "operation (asserted by configuration, not verified here)"
            ),
        }[self]


class SigningBackend(Protocol):
    """
    Everything the attestation path needs, and nothing more.

    Note the absence of any method returning private key material. That is the
    boundary: code above this interface cannot exfiltrate a key because it never
    holds one.
    """

    @property
    def custody_assurance(self) -> CustodyAssurance: ...

    def sign(self, message: bytes) -> bytes: ...

    def public_key_pem(self) -> str: ...


@dataclass
class CustodyReport:
    """Custody posture, for inclusion in a compliance filing."""

    assurance: CustodyAssurance
    backend_name: str
    key_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assurance": self.assurance.value,
            "backend": self.backend_name,
            "key_id": self.key_id,
            "production_suitable": self.assurance.is_production_suitable,
            "rationale": self.assurance.rationale,
        }

    def summary(self) -> str:
        verdict = (
            "adequate for a mandate"
            if self.assurance.is_production_suitable
            else "NOT adequate for a mandate"
        )
        lines = [
            "Signing key custody",
            f"  backend   : {self.backend_name}",
            f"  assurance : {self.assurance.value}",
            f"  key id    : {self.key_id or 'n/a'}",
            f"  verdict   : {verdict}",
            f"  reason    : {self.assurance.rationale}",
        ]
        return "\n".join(lines)


class InProcessSigningBackend:
    """
    Software key in process memory.

    The default, because it needs no infrastructure. Reports IN_PROCESS so no
    downstream consumer can mistake a demo for a deployment.
    """

    name = "in_process_software"

    def __init__(self, private_key: Ed25519PrivateKey | None = None):
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key: Ed25519PublicKey = self._private_key.public_key()
        self._public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    @property
    def custody_assurance(self) -> CustodyAssurance:
        return CustodyAssurance.IN_PROCESS

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def public_key_pem(self) -> str:
        return self._public_pem

    def custody_report(self) -> CustodyReport:
        return CustodyReport(
            assurance=self.custody_assurance,
            backend_name=self.name,
            key_id=None,
        )

    def export_private_key_pem(self) -> str:
        """
        Exists only to make the weakness concrete and testable.

        The presence of this method on this backend and its absence from
        `ExternalSigningBackend` is the difference the report is describing. A
        test asserts the external backend has no such method.
        """
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")


class ExternalSigningBackend:
    """
    Signing delegated across a custody boundary.

    `sign_callable` receives the message bytes and returns the signature. It is
    expected to be a PKCS#11 `C_Sign` wrapper, a cloud KMS `sign` call, or an
    IPC round-trip to a signing daemon. This class never sees key material, so
    a compromise of the agent process yields the ability to *request*
    signatures, not to *take* the key. That is a real difference: requests can
    be rate-limited, logged and revoked.

    `assurance` is supplied by the caller because only the caller knows what is
    on the other end of the callable. Passing HARDWARE_BACKED for a software
    stub is possible and would be a lie; the parameter is named to make that
    lie explicit rather than accidental.
    """

    def __init__(
        self,
        sign_callable: Callable[[bytes], bytes],
        public_key_pem: str,
        assurance: CustodyAssurance = CustodyAssurance.EXTERNAL_PROCESS,
        key_id: str | None = None,
        name: str = "external_signer",
    ):
        if assurance is CustodyAssurance.IN_PROCESS:
            raise ValueError(
                "ExternalSigningBackend cannot report IN_PROCESS custody; use "
                "InProcessSigningBackend if the key is in this process"
            )
        self._sign = sign_callable
        self._public_pem = public_key_pem
        self._assurance = assurance
        self.key_id = key_id
        self.name = name
        self.signature_count = 0
        """Requests made across the boundary. In a real deployment the device
        keeps this number and it is the audit trail; here it demonstrates that
        the count is observable at all, which in-process signing does not give
        you."""

    @property
    def custody_assurance(self) -> CustodyAssurance:
        return self._assurance

    def sign(self, message: bytes) -> bytes:
        self.signature_count += 1
        return self._sign(message)

    def public_key_pem(self) -> str:
        return self._public_pem

    def custody_report(self) -> CustodyReport:
        return CustodyReport(
            assurance=self._assurance,
            backend_name=self.name,
            key_id=self.key_id,
        )


def pkcs11_backend_stub(
    private_key: Ed25519PrivateKey,
    key_id: str = "pkcs11:token=vea;object=agent-signing-key",
) -> ExternalSigningBackend:
    """
    Stand-in for a PKCS#11-backed signer, for exercising the boundary in tests.

    This is a software key behind an external-shaped interface. It reports
    EXTERNAL_PROCESS, never HARDWARE_BACKED, because nothing here is hardware.
    Replacing the closure with a real `C_Sign` call is the entire integration;
    the interface above it does not change, which is the property worth
    demonstrating.
    """
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    def _sign(message: bytes) -> bytes:
        # A real implementation calls out to the token here and never has
        # access to `private_key` in this address space.
        return private_key.sign(message)

    return ExternalSigningBackend(
        sign_callable=_sign,
        public_key_pem=public_pem,
        assurance=CustodyAssurance.EXTERNAL_PROCESS,
        key_id=key_id,
        name="pkcs11_stub",
    )


if __name__ == "__main__":
    software = InProcessSigningBackend()
    print(software.custody_report().summary())
    print()

    external = pkcs11_backend_stub(Ed25519PrivateKey.generate())
    external.sign(b"probe")
    print(external.custody_report().summary())
    print(f"  requests  : {external.signature_count}")
