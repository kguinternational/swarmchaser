# DEMO RUNBOOK: Live Engineering Demonstrator Presentation

**For:** Youth STEM Workshops, Micro Center Reviewers, Grant Committees & Technical Evaluators

## Quickstart Walkthrough (10-Minute Live Presentation)

### Step 1: The Autonomous Engineering Manager
Open the terminal and review project state and task board:
```bash
cat management/PROJECT_STATE.md
cat management/TASK_BOARD.md
```
Show reviewers the four specialized native subagents:
- `cad-fem-engineer` (FreeCAD mechanical & structural)
- `cfd-engineer` (OpenFOAM porous fluid & aerodynamics)
- `pcb-engineer` (KiCad schematic, layout & inrush simulation)
- `assembly-engineer` (Blender exploded views & student manual)

### Step 2: Honest Failure Demonstration (The Fail-First Principle)
Show the honest `FAIL IN RED` on requirement `ROB-02` (Motor inrush current exceeded 14A budget at 18A stall):
```bash
cat management/handoffs/pcb-engineer/HANDOFF_V1.md
```
Demonstrate that unlike deceptive AI systems that fake compliance, our system flags failures transparently and opens a formal Change Request (`CR-003`) to add a soft-start circuit.

### Step 3: W8less Motion Intelligence & Swarm Ranging
Review the zero-GPS, off-grid 10cm relative positioning architecture:
```bash
cat reports/research/w8less_quorium_motion_intelligence.md
```

### Step 4: The 512GB Apple + NVIDIA AI Supercomputing Architecture
Present the dual-architecture hardware grant schedule:
```bash
cat reports/applications/04_microcenter_smiller_mac_starlink_grant.md
```

### Step 5: Verify Continuous Cryptographic Attestation
Run the immutable sealing pipeline:
```bash
python scripts/enforce_immutability.py
```
Demonstrate that all 9 database tables are protected by abort triggers and the release is sealed with Ed25519 signatures.
