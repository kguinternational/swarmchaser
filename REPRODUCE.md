# REPRODUCE: 203x Uplink AI Engineering Run

Follow these instructions to independently verify and reproduce the entire autonomous engineering demonstrator:

## 1. Prerequisites
- **Operating System:** macOS (Apple Silicon) or Linux / Windows (WSL2 Ubuntu 22.04+)
- **Python:** 3.10+ (Tested on Python 3.11)
- **Engineering Toolchain:**
  - FreeCAD (`freecad` / `freecadcmd`)
  - OpenFOAM (v2312 or OpenFOAM-11)
  - KiCad 8.0+ (`kicad-cli`)
  - Blender 4.0+ (`blender`)

## 2. Environment Setup
```bash
git clone https://github.com/kguinternational/swarmchaser.git
cd swarmchaser
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Verify All Tests & Evidence
```bash
# Run the 197 automated verification tests
pytest tests -q

# Run physical engineering verification suite
python -c "
from src.swarm.physical_engineering import PhysicalEngineeringSuite
suite = PhysicalEngineeringSuite()
print('Titan Robotics:', suite.run_subsystem_verification('robotics', {'ROB-01': 46.0, 'ROB-02': 18.0}))
print('Aqua Water:', suite.run_subsystem_verification('water', {'WAT-01': 15.2, 'WAT-02': 0.4}))
print('Zephyr Drones:', suite.run_subsystem_verification('drones', {'UAV-01': 2.3, 'UAV-02': 26.0}))
print('Argus Cameras:', suite.run_subsystem_verification('cameras', {'CAM-01': 30.0, 'CAM-02': 42.0}))
print('W8less MIM:', suite.run_subsystem_verification('positioning', {'POS-01': 9.5, 'POS-02': 14.0}))
"
```

## 4. Verify Immutable Cryptographic Seal
```bash
python scripts/enforce_immutability.py
cat reports/immutable_seal.json
```
