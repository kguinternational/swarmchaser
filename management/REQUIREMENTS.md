# SYSTEM REQUIREMENTS: Emergency Preparedness & Self-Sustainability Lab

All requirements are verified with real tool outputs. Unmet targets trigger `FAIL IN RED`.

| Req ID | Subsystem | Parameter | Target | Tolerance | Unit | Status | Label | Verification Source |
|:---:|:---|:---|:---:|:---:|:---:|:---:|:---:|:---|
| **ROB-01** | Titan (Chassis) | Yield Strength | 45.0 | ±5.0 | MPa | `PASS` | `[SIMULATION]` | FreeCAD FEA CalculiX Solver |
| **ROB-02** | Titan (Powertrain) | Inrush Current | 12.0 | ±2.0 | A | `FAIL IN RED` | `[MEASUREMENT]` | LTSpice Transient Motor Spike (18A measured) |
| **WAT-01** | Aqua (Water) | Porous Zone Flow Rate | 15.0 | ±1.5 | L/min | `PASS` | `[SIMULATION]` | OpenFOAM porousSimpleFoam |
| **WAT-02** | Aqua (Water) | Effluent Turbidity | 0.5 | ±0.3 | NTU | `PASS` | `[MEASUREMENT]` | Digital Spectrophotometer Attestation |
| **AGR-01** | Demeter (Irrigation) | Manifold Pressure | 25.0 | ±3.0 | PSI | `PASS` | `[CALCULATION]` | Darcy-Weisbach Hydraulic Formula |
| **PWR-01** | Helios (Solar) | LiFePO4 Discharge Temp | 35.0 | ±5.0 | °C | `PASS` | `[MEASUREMENT]` | BMS Thermal Telemetry Sensor |
| **UAV-01** | Zephyr (Drones) | Thrust-to-Weight Ratio | 2.2 | ±0.3 | ratio | `PASS` | `[CALCULATION]` | Propeller Dynamic Thrust Model |
| **UAV-02** | Zephyr (Drones) | Flight Endurance | 28.0 | ±4.0 | min | `PASS` | `[SIMULATION]` | Battery Watt-Hour Discharge Curve |
| **CAM-01** | Argus (Cameras) | Thermal Sensor Refresh | 30.0 | ±5.0 | FPS | `PASS` | `[SOURCE]` | FLIR Boson OEM Datasheet |
| **CAM-02** | Argus (Cameras) | Edge YOLO Inference | 40.0 | ±10.0 | ms | `PASS` | `[MEASUREMENT]` | NVIDIA Jetson Orin Nano TensorRT Benchmark |
| **POS-01** | W8less (MIM) | GPS-Denied Accuracy | 10.0 | ±3.0 | cm | `PASS` | `[SOURCE]` | Quorium MIM Peer-to-Peer Ranging Data |
| **POS-02** | W8less (MIM) | Ranging Latency | 15.0 | ±5.0 | ms | `PASS` | `[MEASUREMENT]` | UWB Time-of-Flight Packet Round-Trip |
