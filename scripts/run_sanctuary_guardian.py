#!/usr/bin/env python3
"""Run the 7-Layer Sanctuary Self-Defense & Integrity Audit and write `reports/sanctuary_protection_manifest.json`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm.sanctuary_guardian import SanctuaryGuardian


def main() -> None:
    guardian = SanctuaryGuardian(repo_root=ROOT)
    audit = guardian.run_full_self_defense_audit()

    out_path = ROOT / "reports" / "sanctuary_protection_manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"All 7 defense layers passed: {audit['all_7_defense_layers_passed']}")
    print(f"Codebase Merkle Root SHA-256: {audit['codebase_merkle_root_sha256']}")


if __name__ == "__main__":
    main()
