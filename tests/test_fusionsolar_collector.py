from datetime import timezone
from unittest.mock import Mock

from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.raw_data import RawData


def test_collect_returns_unmodified_api_response_as_raw_data() -> None:
    client = Mock()
    client.station_dn = "station/dn"
    api_response = {
        "data": [{"stationDn": "station/dn", "inverterPower": 42}],
        "success": True,
    }
    client.get_json.return_value = api_response
    collector = FusionSolarCollector(client)

    result = collector.collect()

    client.get_json.assert_called_once_with(
        "/rest/pvms/web/station/v1/station-kpi-list?stationDn=station%2Fdn"
    )
    assert isinstance(result, RawData)
    assert result.source == "fusionsolar"
    assert result.timestamp.tzinfo is timezone.utc
    assert result.payload == api_response
    assert result.payload is api_response
