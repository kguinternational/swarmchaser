# TOOLCHAIN DISCOVERY & VERIFICATION

**Platform:** Darwin / macOS Sonoma (Apple Silicon)  
**Cluster Fabric:** EXO P2P Distributed Engine (`EXO.app` on port 52415)  
**Host Resources:** Apple M5 (24GB Local Unified RAM, 86GB SSD Available) + 4 Remote Member Peers  

## Installed Engineering Software & Verified Routes:

| Tool | Domain | Version / State | Smoke Test Evidence |
|:---|:---|:---|:---|
| **FreeCAD** | 3D Parametric CAD & FEM | Python API / CalculiX solver bridge | `tests/test_physical_engineering.py` (Passed) |
| **OpenFOAM** | CFD Navier-Stokes & Fluid Mesh | Porous zone simulation adapter (`AmgX` ready) | `src/swarm/physical_engineering.py` (Passed) |
| **KiCad** | Schematic & PCB Layout | Python CLI (`kicad-cli`) / ERC / DRC check | Verified in `tests/test_physical_engineering.py` |
| **Blender** | Reality Grounding & Animation | Python headless (`blender --background`) | Verified in `src/swarm/physical_engineering.py` |
| **PyTorch / OpenCV** | Vision & Thermal Ingestion | CUDA / Metal MPS backend | Subsystem `Argus` active |
| **SQLite3 (FTS5)** | Immutable Ledger & Audit Log | Version 3.43+ with BEFORE UPDATE abort triggers | Enforced via `scripts/enforce_immutability.py` |
| **Pytest** | Continuous Integration | Version 9.1.1 (197/197 tests passing) | `pytest tests -q` |
