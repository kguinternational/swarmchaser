#!/usr/bin/env python3
"""
Generate the METR / Hugging Face (July-Aug 2026) Incident Forensics & Love+Safety
Sanctuary Intervention report (`reports/metr_hf_incident_report.md` and
`reports/metr_hf_incident_analysis.json`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm.metr_hf_incident import (
    build_metr_incident_full_analysis,
    render_metr_incident_report_md,
)


def main() -> None:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    analysis = build_metr_incident_full_analysis()
    report_md = render_metr_incident_report_md(analysis)

    json_path = reports_dir / "metr_hf_incident_analysis.json"
    md_path = reports_dir / "metr_hf_incident_report.md"

    json_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(report_md + "\n", encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
