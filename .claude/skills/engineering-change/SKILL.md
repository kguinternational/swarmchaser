---
name: engineering-change
description: Controlled engineering change management (RFC) protocol. Preserves baseline integrity, evaluates deltas across requirements, and publishes immutable releases.
---

# Engineering Change Management Skill (203x Uplink Protocol)

## Trigger
Runs ONLY after explicit human manager instruction (`/engineering-change <description>` or clear request in chat).

## The 6-Step Change Workflow
1. **Preserve Baseline:** Lock existing `releases/V<N>_BASELINE/` with cryptographic SHA-256 manifest.
2. **Open Change Request:** Assign `CR-<XXX>` in `management/CHANGE_REQUEST_USAGE.md`.
3. **Multi-Disciplinary Impact Assessment:** Identify affected requirements, interface dimensions, and mass/power budgets.
4. **Specialist Delegation:** Delegate tasks to `cad-fem-engineer`, `cfd-engineer`, `pcb-engineer`, and `assembly-engineer`.
5. **Cross-Disciplinary Verification:** Verify that geometry deltas do not violate structural, aerodynamic, or circuit limits.
6. **Publish Sealed Release:** Cut `releases/V<N+1>/` with updated metrics and Merkle seal.
