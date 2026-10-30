---
name: engineering-evidence
description: Standardized engineering evidence protocol: requirements, revisions, numerical labels, checksums, locks, and handoffs.
---

# Engineering Evidence Skill (203x Uplink Protocol)

## 1. Ground Rules
- **Honesty Above All:** Never invent successful tool calls, numerical results, supplier specifications, physical tests or production readiness.
- **Mandatory Numerical Labels:** Every number in any report or handoff must be labeled:
  - `[SOURCE]`: Directly from a manufacturer datasheet or academic paper.
  - `[CALCULATION]`: From a reproducible mathematical formula or script.
  - `[SIMULATION]`: From a numerical solver (CalculiX, OpenFOAM, LTSpice).
  - `[MEASUREMENT]`: From physical sensor telemetry or benchmark test.
  - `[ASSUMPTION]`: Unverified initial design target.
- **Status Words:** Only use `PASS`, `PARTIAL`, `FAIL`, `BLOCKED`, and `NOT RUN`.
- **Never Relabel a Fail:** An out-of-spec parameter is recorded honestly as `FAIL IN RED`.

## 2. File Lock Protocol
Before modifying an shared application file, check `management/locks/<filename>.lock`.
If unowned, write your agent name and timestamp. Release lock immediately upon completion.
