import json
import threading
from urllib.request import urlopen

from hedp.web.server import create_dashboard_server, demonstration_snapshot


def test_demonstration_snapshot_contains_no_household_identifiers():
    snapshot = demonstration_snapshot()
    payload = json.dumps(snapshot)

    assert snapshot["mode"] == "shadow"
    assert snapshot["schema"] == "hestia.interface.demo.v1"
    assert len(snapshot["energy"]["history"]) >= 12
    assert "192.168." not in payload
    assert "device_id" not in payload
    assert "serial" not in payload


def test_dashboard_server_serves_page_assets_and_summary():
    server = create_dashboard_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base_url}/", timeout=2) as response:  # noqa: S310
            page = response.read().decode()
            assert response.status == 200
            assert "<title>HESTIA</title>" in page
            assert "SHADOW" in page
            assert "太陽光の発電推移" in page
        with urlopen(f"{base_url}/app.css", timeout=2) as response:  # noqa: S310
            assert response.status == 200
            assert b"--accent: #0a84ff" in response.read()
        with urlopen(f"{base_url}/api/summary", timeout=2) as response:  # noqa: S310
            summary = json.load(response)
            assert summary["mode"] == "shadow"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
