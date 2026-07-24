from datetime import datetime, timezone
from unittest.mock import Mock

from hedp.application import Application
from hedp.configuration import Configuration, ModbusConfiguration
from hedp.storage import RawData, Record


def test_modbus_configuration_accepts_sumicore_environment(monkeypatch):
    monkeypatch.setenv(
        "SUMICORE_FUSIONSOLAR_MODBUS_HOST", "192.168.1.10"
    )
    monkeypatch.setenv("SUMICORE_FUSIONSOLAR_MODBUS_PORT", "502")
    monkeypatch.setenv("SUMICORE_FUSIONSOLAR_MODBUS_UNIT_ID", "1")
    monkeypatch.setenv(
        "SUMICORE_FUSIONSOLAR_MODBUS_EXPECTED_SERIAL", "test-device"
    )
    assert Configuration.modbus_from_environment() == ModbusConfiguration(
        host="192.168.1.10",
        port=502,
        unit_id=1,
        expected_serial="test-device",
    )


def test_run_modbus_preserves_raw_before_records():
    raw = RawData(
        source="fusionsolar_modbus_tcp",
        timestamp=datetime.now(timezone.utc),
        payload={"ranges": []},
    )
    records = [
        Record(
            source=raw.source,
            timestamp=raw.timestamp,
            metric="storage_soc",
            value=55.0,
            unit="%",
        )
    ]
    storage = Mock()
    collector = Mock()
    collector.collect.return_value = raw
    builder = Mock()
    builder.build.return_value = records
    application = Application(
        None,
        storage,
        None,
        modbus_collector=collector,
        modbus_record_builder=builder,
    )

    assert application.run_modbus() == raw
    storage.save_rawdata.assert_called_once_with(raw)
    storage.save_records.assert_called_once_with(records)


def test_realtime_runs_modbus_before_cloud_authentication_return():
    raw = RawData(
        source="fusionsolar_modbus_tcp",
        timestamp=datetime.now(timezone.utc),
        payload={"ranges": []},
    )
    application = Application(
        None,
        Mock(),
        None,
        device_realtime_collector=Mock(),
        modbus_collector=Mock(),
        modbus_record_builder=Mock(),
    )
    application.run_modbus = Mock(return_value=raw)
    application.run_device_realtime = Mock(
        return_value=(
            [],
            [("device", "RuntimeError: FusionSolar requires CAPTCHA or a verification code")],
        )
    )

    result = application.run_realtime_snapshot(
        ["device"], "battery", "signals"
    )

    assert result["modbus"] == raw
    assert result["authentication_required"] is True
    application.run_modbus.assert_called_once_with()
