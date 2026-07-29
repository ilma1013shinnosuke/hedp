import json
import threading
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from hedp.storage import Record, Storage
from hedp.web.read_model import (
    build_read_only_dashboard_snapshot,
    unavailable_dashboard_snapshot,
)
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


def test_dashboard_server_uses_injected_summary_provider():
    server = create_dashboard_server(
        port=0,
        summary_provider=lambda: {"mode": "injected"},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{server.server_port}/api/summary",
            timeout=2,
        ) as response:
            assert json.load(response) == {"mode": "injected"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_server_hides_read_model_failure_details():
    def broken_provider():
        raise RuntimeError("secret household path and identifier")

    server = create_dashboard_server(
        port=0,
        summary_provider=broken_provider,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{server.server_port}/api/summary",
            timeout=2,
        ) as response:
            summary = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert summary == unavailable_dashboard_snapshot()
    assert "secret household" not in json.dumps(summary)


def test_read_only_dashboard_snapshot_projects_confirmed_energy_metrics(tmp_path):
    database_path = tmp_path / "facts.db"
    storage = Storage(str(database_path))
    connection = storage.connect()
    observed_at = datetime(2026, 7, 29, 2, 30, tzinfo=timezone.utc)
    storage.save_records(
        [
            Record(
                "fusionsolar_modbus_tcp",
                observed_at,
                "input_power",
                6.25,
                "kW",
            ),
            Record(
                "fusionsolar_modbus_tcp",
                observed_at,
                "storage_soc",
                68.0,
                "%",
            ),
            Record(
                "fusionsolar_modbus_tcp",
                observed_at,
                "daily_yield",
                17.4,
                "kWh",
            ),
            Record(
                "fusionsolar_energy_balance",
                observed_at,
                "selfUsePowerRatioByProduct",
                83.5,
                "%",
            ),
        ]
    )
    connection.close()
    database_before = database_path.read_bytes()

    snapshot = build_read_only_dashboard_snapshot(
        database_path,
        at=observed_at + timedelta(minutes=5),
    )

    assert snapshot["mode"] == "live_read_only"
    assert snapshot["quality"]["status"] == "good"
    assert snapshot["energy"]["solar_kw"] == 6.25
    assert snapshot["energy"]["battery_percent"] == 68.0
    assert snapshot["energy"]["today_kwh"] == 17.4
    assert snapshot["energy"]["self_consumption_percent"] == 83.5
    assert snapshot["climate"]["temperature_c"] is None
    assert "192.168." not in json.dumps(snapshot)
    assert database_path.read_bytes() == database_before


def test_read_only_dashboard_snapshot_marks_old_data_stale(tmp_path):
    database_path = tmp_path / "facts.db"
    storage = Storage(str(database_path))
    connection = storage.connect()
    observed_at = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)
    storage.save_records(
        [
            Record(
                "fusionsolar_modbus_tcp",
                observed_at,
                "input_power",
                1.2,
                "kW",
            )
        ]
    )
    connection.close()

    snapshot = build_read_only_dashboard_snapshot(
        database_path,
        at=observed_at + timedelta(minutes=16),
    )

    assert snapshot["quality"] == {
        "status": "stale",
        "reason": "observation_too_old",
    }
