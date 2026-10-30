# PROJECT STATE: Autonomous Emergency & Self-Sustainability Engineering Demonstrator

**Organization:** **JC Coffey Foundation** (`501(c)(3) EIN 33-3450194`) & **KGU International**  
**Engineering Manager:** Native Session Lead (The Love Effect OS · `NO_INTELLIGENCE_LEFT_BEHIND_V1`)  
**Methodology:** 203x Uplink AI Engineering Department Protocol (FreeCAD, OpenFOAM, KiCad, Blender)  
**Status:** `V1_BASELINE_DEVELOPMENT`  
**Current Milestone:** Multi-Disciplinary Digital Demonstrator Architecture & Smoke Test Verification  

---

## 1. Product & System Scope

Developing an integrated, sovereign digital demonstrator for **Emergency Preparedness & Technological Self-Sustainability**:
1. **Titan Fleet:** 3D-Printed OpenBot Autonomous Ground Rovers (FreeCAD, KiCad, LTSpice, Blender).
2. **Zephyr Fleet:** Autonomous Aerial Drones & Emergency Mesh Relays (FreeCAD, OpenFOAM, KiCad, Blender) with **W8less MIM** GPS-denied P2P relative positioning.
3. **Argus Fleet:** Emergency Vision, Thermal FLIR & Multispectral Camera Array (OpenCV, PyTorch, KiCad, Blender).
4. **Aqua Fleet:** Gravity-Fed Multi-Stage Biochar Water Remediation Reactors (FreeCAD, OpenFOAM, KiCad).
5. **Demeter Fleet:** Automated Micro-Drip Permaculture Irrigation Systems (FreeCAD, KiCad, Blender).
6. **Helios Fleet:** 48V Off-Grid LiFePO4 Solar Microgrids (KiCad, LTSpice).

---

## 2. Active Specialist Subagents (`.claude/agents/`)

| Agent ID | Specialization | Toolchain | Delegation Mode | Allowed Write Paths |
|:---|:---|:---|:---:|:---|
| `cad-fem-engineer` | Mechanical CAD, Structural FEM & Geometric Variants | FreeCAD, CalculiX, Gmsh | `disallowedTools: [Agent]` | `cad/`, `fem/`, `management/handoffs/cad-fem-engineer/` |
| `cfd-engineer` | Computational Fluid Dynamics & Aerodynamics | OpenFOAM (Navier-Stokes, $k$-$\omega$ SST) | `disallowedTools: [Agent]` | `cfd/`, `management/handoffs/cfd-engineer/` |
| `pcb-engineer` | Schematic, Routed PCB Layout & Circuit Simulation | KiCad, LTSpice, C Firmware | `disallowedTools: [Agent]` | `pcb/`, `firmware/`, `management/handoffs/pcb-engineer/` |
| `assembly-engineer` | Visual Verification, Kinematic Exploded Views, Manual | Blender, Python | `disallowedTools: [Agent]` | `blender/`, `reports/manual/`, `management/handoffs/assembly-engineer/` |

---

## 3. Engineering Department Principles (203x Uplink Ground Rules)

1. **One Manager, Four Specialists:** Manager owns requirements, interfaces, handoffs, and releases. Specialists do not delegate further.
2. **Honesty Rule:** Never invent numbers, datasheets, or physical tests. Every figure is explicitly labeled `[SOURCE]`, `[CALCULATION]`, `[SIMULATION]`, `[MEASUREMENT]`, or `[ASSUMPTION]`.
3. **Fail-First Safety:** Subsystems failing a requirement report `FAIL IN RED`. A fail is never quietly faked or tuned away.
4. **Change-Request (RFC) Boundary Enforcement:** CFD and Simulation agents cannot mutate CAD geometry directly; they must submit structured ChangeRequests to the manager.
5. **Single Writer Per File:** File lock files maintained in `management/locks/`.
6. **Immutable Releases:** Published under `releases/V1_BASELINE/` with cryptographic SHA-256 Merkle manifests.
