from datetime import date, datetime, timezone
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import pytest

from hedp.fusionsolar_collector import FusionSolarCollector
from hedp.raw_data import RawData


def test_collect_for_date_uses_midnight_and_unmodified_response() -> None:
    client = Mock()
    client.station_dn = "station/dn"
    api_response = {
        "data": [{"stationDn": "station/dn", "inverterPower": 42}],
        "success": True,
    }
    client.post_json.return_value = api_response
    collector = FusionSolarCollector(client)

    result = collector.collect_for_date(date(2026, 7, 20))

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
        "statTime": int(
            datetime(
                2026, 7, 20, tzinfo=ZoneInfo("Asia/Tokyo")
            ).timestamp()
            * 1000
        ),
        "statType": "1",
        "station": "1",
        "timeZone": 9,
        "timeZoneStr": "Asia/Tokyo",
    }
    assert isinstance(result, RawData)
    assert result.source == "fusionsolar"
    assert result.timestamp.tzinfo is timezone.utc
    assert result.payload is api_response
    assert result.target_date == date(2026, 7, 20)


def test_collect_for_date_preserves_empty_api_response() -> None:
    client = Mock()
    client.station_dn = "station/dn"
    api_response = {"data": {"list": []}}
    client.post_json.return_value = api_response

    result = FusionSolarCollector(client).collect_for_date(date(2026, 7, 20))

    assert result.target_date == date(2026, 7, 20)
    assert result.payload is api_response


def test_collect_uses_today_in_tokyo() -> None:
    client = Mock()
    collector = FusionSolarCollector(client)
    raw_data = Mock(spec=RawData)
    collector.collect_for_date = Mock(return_value=raw_data)

    with patch("hedp.fusionsolar_collector.datetime") as datetime_class:
        datetime_class.now.return_value = datetime(
            2026, 7, 20, 23, 30, tzinfo=ZoneInfo("Asia/Tokyo")
        )

        result = collector.collect()

    collector.collect_for_date.assert_called_once_with(date(2026, 7, 20))
    assert result is raw_data


def test_collect_range_includes_both_ends_in_date_order() -> None:
    client = Mock()
    client.station_dn = "station/dn"
    responses = [{"day": day} for day in (20, 21, 22)]
    client.post_json.side_effect = responses
    collector = FusionSolarCollector(client)
    collector.collect_for_date = Mock(wraps=collector.collect_for_date)

    results = collector.collect_range(date(2026, 7, 20), date(2026, 7, 22))

    assert collector.collect_for_date.call_args_list == [
        call(date(2026, 7, 20)),
        call(date(2026, 7, 21)),
        call(date(2026, 7, 22)),
    ]
    assert [result.payload for result in results] == responses
    assert all(
        result.payload is response
        for result, response in zip(results, responses)
    )


def test_collect_range_rejects_reverse_range() -> None:
    collector = FusionSolarCollector(Mock())

    with pytest.raises(ValueError):
        collector.collect_range(date(2026, 7, 21), date(2026, 7, 20))
