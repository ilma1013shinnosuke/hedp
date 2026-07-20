from datetime import datetime, timezone
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.raw_data import RawData


def test_collect_returns_unmodified_api_response_as_raw_data() -> None:
    client = Mock()
    client.station_dn = "station/dn"
    api_response = {
        "data": [{"stationDn": "station/dn", "inverterPower": 42}],
        "success": True,
    }
    client.post_json.return_value = api_response
    collector = FusionSolarCollector(client)

    result = collector.collect()

    client.post_json.assert_called_once()
    url, body = client.post_json.call_args.args
    assert url == "/rest/pvms/web/report/v1/station/station-kpi-list"
    assert body == {
        "currencyUnit": "¥",
        "counterIDs": [
            "productPower",
            "inverterPower",
            "onGridPower",
            "buyPower",
            "powerProfit",
        ],
        "moList": [{"moType": 20801, "moString": "station/dn"}],
        "orderBy": "fmtCollectTimeStr",
        "page": 1,
        "pageSize": 100,
        "sort": "asc",
        "statDim": "2",
        "statTime": body["statTime"],
        "statType": "1",
        "station": "1",
        "timeZone": 9,
        "timeZoneStr": "Asia/Tokyo",
    }
    stat_time = datetime.fromtimestamp(
        body["statTime"] / 1000, ZoneInfo("Asia/Tokyo")
    )
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    assert stat_time.date() == now.date()
    assert stat_time.hour == 0
    assert stat_time.minute == 0
    assert stat_time.second == 0
    assert stat_time.microsecond == 0
    assert isinstance(result, RawData)
    assert result.source == "fusionsolar"
    assert result.timestamp.tzinfo is timezone.utc
    assert result.payload == api_response
    assert result.payload is api_response
