from src.swarm.physical_engineering import (
    EngineeringRequirement,
    PhysicalEngineeringSuite,
    VerificationStatus,
)


def test_engineering_honest_failure_reporting():
    """Verify that when a strength test fails, it reports FAIL in red rather than being faked."""
    req = EngineeringRequirement(
        req_id="TEST-01",
        subsystem="chassis",
        parameter="yield_strength",
        target_value=50.0,
        tolerance=5.0,
        unit="MPa",
    )
    # Measured is 30 MPa (severely below limit [45, 55])
    status = req.evaluate(30.0)
    assert status == VerificationStatus.FAIL
    assert "FAIL IN RED" in req.notes
    assert req.measured_value == 30.0


def test_subsystem_verification_suite():
    suite = PhysicalEngineeringSuite()
    # Test Titan robotics
    res_robotics = suite.run_subsystem_verification("robotics", {
        "ROB-01": 46.0,  # PASS (target 45 +- 5)
        "ROB-02": 18.0,  # FAIL (target 12 +- 2) -> inrush exceeded
    })
    assert res_robotics["passed"] == 1
    assert res_robotics["failed_honestly_in_red"] == 1

    # Test Aqua water remediation
    res_water = suite.run_subsystem_verification("water", {
        "WAT-01": 15.2,  # PASS
        "WAT-02": 0.4,   # PASS
    })
    assert res_water["passed"] == 2
    assert res_water["failed_honestly_in_red"] == 0

    # Test Zephyr drones
    res_drones = suite.run_subsystem_verification("drones", {
        "UAV-01": 2.3,   # PASS (2.2 +- 0.3)
        "UAV-02": 26.0,  # PASS (28.0 +- 4.0)
    })
    assert res_drones["passed"] == 2
    assert res_drones["failed_honestly_in_red"] == 0

    # Test Argus emergency cameras
    res_cameras = suite.run_subsystem_verification("cameras", {
        "CAM-01": 30.0,  # PASS (30.0 +- 5.0)
        "CAM-02": 42.0,  # PASS (40.0 +- 10.0)
    })
    assert res_cameras["passed"] == 2
    assert res_cameras["failed_honestly_in_red"] == 0

    # Test W8less MIM GPS-denied relative positioning
    res_pos = suite.run_subsystem_verification("positioning", {
        "POS-01": 9.5,   # PASS (10.0 +- 3.0 cm)
        "POS-02": 14.0,  # PASS (15.0 +- 5.0 ms)
    })
    assert res_pos["passed"] == 2
    assert res_pos["failed_honestly_in_red"] == 0

    # Test Meshlink Wi-Fi HaLow & self-funding gateway
    res_meshlink = suite.run_subsystem_verification("meshlink", {
        "WIFI-01": 2.1,   # PASS (2.0 +- 0.5 km)
        "WIFI-02": 115.0, # PASS (120.0 +- 30.0 ms)
    })
    assert res_meshlink["passed"] == 2
    assert res_meshlink["failed_honestly_in_red"] == 0
