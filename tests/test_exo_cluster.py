from src.swarm.exo_cluster import ExoClusterManager


def test_exo_cluster_probe():
    manager = ExoClusterManager()
    status = manager.probe_cluster()
    assert status.is_online is True
    assert status.node_id is not None
    assert "12D3Koo" in status.node_id
    assert status.available_model_count > 0
    assert status.endpoint == "http://127.0.0.1:52415"
