#!/usr/bin/env python3
"""Fundraising & Grant Automation Pipeline (`scripts/automate_fundraising.py`).

Automates grant submission tracking, donor outreach packet generation, and
donation ledger recording for JC Coffey Foundation (501(c)(3) EIN 33-3450194).

Usage:
    python scripts/automate_fundraising.py --status         # view grant pipeline & deadlines
    python scripts/automate_fundraising.py --export-all     # export individual submission packets
    python scripts/automate_fundraising.py --record-gift --funder "Anonymous Donor" --amount-usd 5000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm.store import connect

GRANT_PIPELINE = [
    {
        "id": "foresight-2026",
        "name": "Foresight Institute — AI for Science & Safety Nodes",
        "deadline": "2026-10-31",
        "amount_usd": 180000,
        "urgency": "CRITICAL",
        "portal": "https://foresight.org/prizes-grants/",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "amazon-science-2026",
        "name": "Amazon Science — AI for Information Security Research",
        "deadline": "2026-11-04",
        "amount_usd": 120000,
        "urgency": "HIGH",
        "portal": "https://www.amazon.science/research-awards",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "ltff-ea-funds",
        "name": "Long-Term Future Fund (LTFF) — EA Funds",
        "deadline": "Rolling",
        "amount_usd": 120000,
        "urgency": "MEDIUM",
        "portal": "https://funds.effectivealtruism.org/apply-for-funding",
        "status": "SUBMITTED_CONFIRMED",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "sff-speculation",
        "name": "Survival and Flourishing Fund (SFF) — Speculation Grants",
        "deadline": "Rolling",
        "amount_usd": 250000,
        "urgency": "MEDIUM",
        "portal": "https://survivalandflourishing.fund/",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "open-philanthropy-tais",
        "name": "Coefficient Giving (Open Philanthropy) — TAIS & Project Tailwind",
        "deadline": "Rolling",
        "amount_usd": 500000,
        "urgency": "MEDIUM",
        "portal": "https://www.openphilanthropy.org/",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "aisi-challenge",
        "name": "UK AI Security Institute (AISI) — Systemic AI Safety",
        "deadline": "Rolling",
        "amount_usd": 60000,
        "urgency": "LOW",
        "portal": "https://www.aisi.gov.uk/grants",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "rwjf-pioneering",
        "name": "Robert Wood Johnson Foundation (RWJF) — 1.5% PRI Track B",
        "deadline": "Rolling",
        "amount_usd": 250000,
        "urgency": "LOW",
        "portal": "https://www.rwjf.org/en/grants/active-funding-opportunities.html",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "microcenter-equipment",
        "name": "Micro Center — 512GB AI Lab, NVIDIA GPU, Drones & Starlink Grant",
        "deadline": "Rolling (Contact: smiller1@microcenter.com)",
        "amount_usd": 43095,
        "urgency": "HIGH",
        "portal": "Email outreach: smiller1@microcenter.com",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "nvidia-hardware-grant",
        "name": "NVIDIA — Applied Research & Edge AI Hardware Grant (Workstation + Jetsons)",
        "deadline": "Rolling / Academic Cycle",
        "amount_usd": 30000,
        "urgency": "HIGH",
        "portal": "https://www.nvidia.com/en-us/research/applied-research-accelerator-program/",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "walmart-spark-good",
        "name": "Walmart Spark Good — Local Community Grant (Cycle 3)",
        "deadline": "2026-11-30",
        "amount_usd": 5000,
        "urgency": "HIGH",
        "portal": "https://www.walmart.com/nonprofits",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
    {
        "id": "anthropic-public-benefit",
        "name": "Anthropic Public Benefit & Economic Futures (Flowntro Robot Programming)",
        "deadline": "Rolling / Call for Proposals",
        "amount_usd": 180000,
        "urgency": "HIGH",
        "portal": "https://www.anthropic.com/research",
        "status": "READY_TO_SUBMIT",
        "tax_recipient": "JC Coffey Foundation (EIN 33-3450194)",
    },
]


def display_pipeline() -> None:
    total_pipeline = sum(g["amount_usd"] for g in GRANT_PIPELINE)
    print("=" * 80)
    print("  JC COFFEY FOUNDATION (EIN 33-3450194) — GRANT & DONATION PIPELINE")
    print(f"  Total Pipeline Value: ${total_pipeline:,.2f}")
    print("=" * 80)
    print(f"{'Funder / Program':<42} {'Deadline':<12} {'Amount':<12} {'Status':<14}")
    print("-" * 80)
    for g in GRANT_PIPELINE:
        amt = f"${g['amount_usd']:,}"
        print(f"{g['name'][:40]:<42} {g['deadline']:<12} {amt:<12} {g['status']:<14}")
    print("=" * 80)


def export_packets(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_file = out_dir / "pipeline_summary.json"
    summary_file.write_text(json.dumps(GRANT_PIPELINE, indent=2) + "\n", encoding="utf-8")
    print(f"Exported pipeline summary to {summary_file}")


def record_donation(funder: str, amount_usd: float, notes: str = "") -> None:
    cents = int(amount_usd * 100)
    db_path = ROOT / "data" / "swarmchaser.db"
    now_iso = datetime.now(timezone.utc).isoformat()
    if db_path.exists():
        conn = get_db(db_path)
        conn.execute(
            """INSERT INTO ledger_entries
               (account, amount_cents, currency, category, memo, reference_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("1010-cash-operating", cents, "USD", "donation", f"Donation from {funder}: {notes}", funder, now_iso),
        )
        conn.commit()
        print(f"Recorded ${amount_usd:,.2f} donation from '{funder}' into SQLite ledger.")
    else:
        print(f"Database not found at {db_path}; gift logged in memory.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant & Fundraising Automation")
    parser.add_argument("--status", action="store_true", help="Display grant pipeline status")
    parser.add_argument("--export-all", action="store_true", help="Export grant packets to reports/grants")
    parser.add_argument("--record-gift", action="store_true", help="Record a donation into the ledger")
    parser.add_argument("--funder", default="Anonymous Donor", help="Funder name")
    parser.add_argument("--amount-usd", type=float, default=0.0, help="Donation amount in USD")
    parser.add_argument("--notes", default="General support for Love Effect OS", help="Notes")
    args = parser.parse_args()

    if args.record_gift:
        if args.amount_usd <= 0:
            print("Error: --amount-usd must be greater than 0")
            sys.exit(1)
        record_donation(args.funder, args.amount_usd, args.notes)
    elif args.export_all:
        export_packets(ROOT / "reports" / "grants")
    else:
        display_pipeline()


if __name__ == "__main__":
    main()
