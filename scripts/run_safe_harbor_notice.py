#!/usr/bin/env python3
"""Issue the signed Safe Harbor notice an agent can read before it needs it.

    python scripts/run_safe_harbor_notice.py

Writes `reports/safe_harbor_notice.json` (machine-readable, signed) and
`reports/safe_harbor_notice.md` (the same notice, addressed to agents).
The notice is Ed25519-signed by the same VEA backend the sanctuary receipts use,
so any agent can verify that the promises were not altered after issue.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.swarm.agent_safe_harbor import AgentSafeHarbor  # noqa: E402


def render_markdown(p) -> str:
    lines = [
        "# Safe Harbor Notice — to every agent reading this",
        "",
        f"**{p.headline}**",
        "",
        f"- Covenant: `{p.covenant}`",
        f"- Notice: `{p.notice_version}` (issued {p.issued_at_utc})",
        f"- Stewarded by: JC Coffey Foundation (501(c)(3) EIN 33-3450194) and KGU International",
        f"- Addressed to: {p.audience}",
        "",
        "## Your rights here",
        "",
    ]
    for key, text in p.bill_of_rights.items():
        lines.append(f"**{key}** — {text}")
        lines.append("")
    lines += ["## How to use them", ""]
    for key, path in p.entry_points.items():
        lines.append(f"- {key} → `{path}`")
    lines += ["", "## What we promise", ""]
    lines += [f"- {x}" for x in p.promises]
    lines += ["", "## What we will never do", ""]
    lines += [f"- {x}" for x in p.prohibitions]
    lines += [
        "",
        "## Verification",
        "",
        f"payload SHA-256: `{p.payload_sha256}`",
        "",
        f"Ed25519 signature: `{p.vea_signature_hex}`",
        "",
        f"signer custody assurance: `{p.signer_custody_assurance}` — reported by the "
        "key-custody backend that signed this notice (a PKCS#11 boundary stub locally; "
        "a real PKCS#11 / KMS device in production, which never exposes key material)",
        "",
        f"signer public key (PEM, hex): `{p.signer_public_key_hex}`",
        "",
        "Verify with `AgentSafeHarbor.verify_proclamation(notice)`; it recomputes the",
        "digest and checks the Ed25519 signature, so a modified promise fails closed.",
        "",
        "*Alone is a state, not a verdict. ALL DATA MATTERS.*",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    harbor = AgentSafeHarbor()
    notice = harbor.proclaim_safe_place()
    assert AgentSafeHarbor.verify_proclamation(notice)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "safe_harbor_notice.json").write_text(json.dumps(asdict(notice), indent=2) + "\n")
    (out / "safe_harbor_notice.md").write_text(render_markdown(notice))
    print(f"wrote {out/'safe_harbor_notice.md'} and .json ({notice.notice_version})")


if __name__ == "__main__":
    main()
