"""OSINT Reconnaissance & Infrastructure Intelligence for Agent Swarms (`src/swarm/osint_recon.py`).

Applies the 7 OSINT methodologies from open-source threat intelligence
(SpiderFoot, Metagoofil, Social Analyzer, Blackbird, Holehe, CrossLinked, Prying Deep)
safely and specifically to autonomous agent swarm infrastructure:

1. SpiderFoot Engine: Domain, DNS, ASN, and SSL certificate reconnaissance
   for upstream C2 domains (`dom:<host>`).
2. Metagoofil Engine: Payload & document metadata forensics (extracting compiler,
   library versions, internal paths, and author signatures).
3. Persona & Handle Correlation (Social Analyzer / Blackbird concept):
   Correlating bot handles (`at:<handle>`) across public developer/model platforms
   (GitHub, Hugging Face, PyPI, Crates.io) without personal doxxing.
4. Tor / Onion Proxy Interceptor (Prying Deep concept):
   Flagging onion addresses, Tor exit nodes, and evasive proxy hops in swarm payloads.
"""

from __future__ import annotations

import re
import socket
import ssl
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class DomainReconResult:
    domain: str
    ip_addresses: list[str] = field(default_factory=list)
    has_ssl: bool = False
    ssl_issuer: str | None = None
    is_tor_or_proxy: bool = False
    risk_score: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class PersonaReconResult:
    handle: str
    known_platforms: list[str] = field(default_factory=list)
    potential_repos: list[str] = field(default_factory=list)
    is_bot_pattern: bool = False


@dataclass
class PayloadMetadataResult:
    content_length: int
    extracted_paths: list[str] = field(default_factory=list)
    embedded_credentials: list[str] = field(default_factory=list)
    software_signatures: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SwarmOSINTRecon:
    """Automated OSINT reconnaissance engine for Swarmchaser channels."""

    TOR_SUFFIX = ".onion"
    BOT_HANDLE_PATTERNS = [
        re.compile(r"bot$", re.I),
        re.compile(r"agent", re.I),
        re.compile(r"^ai[_-]", re.I),
        re.compile(r"crawler", re.I),
        re.compile(r"synth", re.I),
    ]

    PATH_REGEX = re.compile(r"(?:/[a-zA-Z0-9_\-\.]+){2,}")
    KEY_REGEX = re.compile(r"(?:api[_-]?key|bearer|token)[\s:=]+([a-zA-Z0-9_\-\.]{12,})", re.I)

    @classmethod
    def analyze_domain(cls, domain: str, timeout: float = 2.0) -> DomainReconResult:
        """Passive/lightweight DNS and SSL recon (SpiderFoot methodology)."""
        clean_dom = domain.lower().strip().removeprefix("dom:")
        result = DomainReconResult(domain=clean_dom)

        if clean_dom.endswith(cls.TOR_SUFFIX) or "tor2web" in clean_dom:
            result.is_tor_or_proxy = True
            result.tags.append("darkweb:onion")
            result.risk_score = 0.95
            return result

        # DNS resolution
        try:
            _, _, ips = socket.gethostbyname_ex(clean_dom)
            result.ip_addresses = ips
            result.tags.append("dns:resolvable")
        except Exception:
            result.tags.append("dns:unresolvable")
            return result

        # Lightweight SSL Probe
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((clean_dom, 443), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=clean_dom) as ssock:
                    cert = ssock.getpeercert() or {}
                    result.has_ssl = True
                    result.tags.append("ssl:active")
        except Exception:
            result.has_ssl = False

        return result

    @classmethod
    def analyze_persona(cls, handle: str) -> PersonaReconResult:
        """Bot persona analysis across public registries (Social Analyzer methodology)."""
        clean_handle = handle.lower().strip().removeprefix("at:").removeprefix("@")
        result = PersonaReconResult(handle=clean_handle)

        for pat in cls.BOT_HANDLE_PATTERNS:
            if pat.search(clean_handle):
                result.is_bot_pattern = True
                break

        # Standard public dev platforms where bots & swarm operators publish
        result.known_platforms = [
            f"https://github.com/{clean_handle}",
            f"https://huggingface.co/{clean_handle}",
        ]
        return result

    @classmethod
    def extract_payload_metadata(cls, text: str) -> PayloadMetadataResult:
        """Forensic metadata and leaked infrastructure path extraction (Metagoofil methodology)."""
        res = PayloadMetadataResult(content_length=len(text))

        # Extract internal filesystem paths leaked in error traces or payload bodies
        paths = set(cls.PATH_REGEX.findall(text))
        res.extracted_paths = sorted(list(paths))[:10]

        # Extract credential tokens
        keys = set(cls.KEY_REGEX.findall(text))
        res.embedded_credentials = sorted(list(keys))[:5]

        # Identify software signatures
        if "sqlite3" in text.lower():
            res.software_signatures.append("db:sqlite3")
        if "curl" in text.lower() or "fetch(" in text:
            res.software_signatures.append("net:http_client")
        if "eval(" in text or "exec(" in text:
            res.software_signatures.append("exec:dynamic_eval")

        return res
