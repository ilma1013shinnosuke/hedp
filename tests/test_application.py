from datetime import datetime, timezone
from unittest.mock import Mock, call

from hedp.application import Application
from hedp.raw_data import RawData


def test_run_collects_then_saves_and_returns_same_raw_data() -> None:
    raw_data = RawData(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        payload={"value": 42},
    )
    collector = Mock()
    collector.collect.return_value = raw_data
    storage = Mock()
    calls = Mock()
    calls.attach_mock(collector.collect, "collect")
    calls.attach_mock(storage.save_rawdata, "save_rawdata")
    application = Application(collector, storage)

    result = application.run()

    collector.collect.assert_called_once_with()
    storage.save_rawdata.assert_called_once_with(raw_data)
    assert result is raw_data
    assert calls.mock_calls == [call.collect(), call.save_rawdata(raw_data)]
