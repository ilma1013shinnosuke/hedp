from datetime import date, datetime, timezone
from unittest.mock import Mock, call, patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from hedp.fusionsolar_energy_balance_collector import (
    FusionSolarEnergyBalanceCollector,
)


def test_collect_for_date_gets_full_response_with_confirmed_query() -> None:
    client = Mock()
    client.station_dn = "NE=33812827"
    x_axis = [
        f"2026-07-20 {minutes // 60:02d}:{minutes % 60:02d}"
        for minutes in range(0, 24 * 60, 5)
    ]
    series_names = [
        "productPower",
        "dieselProductPower",
        "mainsUsePower",
        "onGridPower",
        "disGridPower",
        "usePower",
        "selfUsePower",
        "chargePower",
        "dischargePower",
        "radiationDosePower",
    ]
    series = {
        name: ["0.000"] * 287 + ["--"] for name in series_names
    }
    data = {
        "stationDn": "NE=33812827",
        "stationTimezone": "Asia/Tokyo",
        "clientTimezone": "Asia/Shanghai",
        "existInverter": True,
        "existMeter": True,
        "existEnergyStore": True,
        "existCharge": False,
        "existIrradiation": False,
        "existUsePower": False,
        **series,
        "totalProductPower": "42.0",
        "totalSelfUsePower": "30.0",
        "totalOnGridPower": "12.0",
        "totalBuyPower": "3.0",
        "totalUsePower": "33.0",
        "selfProvide": "90.0",
        "onGridPowerRatio": "28.5",
        "selfUsePowerRatioByProduct": "71.5",
        "buyPowerRatio": "9.0",
        "selfUsePowerRatioByUse": "90.9",
        "xAxis": x_axis,
    }
    api_response = {"success": True, "data": data, "failCode": 0}
    client.get_json.return_value = api_response
    request_time = datetime(2026, 7, 20, 1, 2, 3, tzinfo=timezone.utc)
    collected_at = datetime(2026, 7, 20, 1, 2, 4, tzinfo=timezone.utc)

    with patch(
        "hedp.fusionsolar_energy_balance_collector.datetime"
    ) as datetime_class:
        datetime_class.combine.side_effect = datetime.combine
        datetime_class.now.side_effect = [request_time, collected_at]
        result = FusionSolarEnergyBalanceCollector(client).collect_for_date(
            date(2026, 7, 20)
        )

    client.get_json.assert_called_once()
    request_url = client.get_json.call_args.args[0]
    parsed = urlsplit(request_url)
    assert parsed.path == (
        "/rest/pvms/web/station/v1/overview/energy-balance"
    )
    assert parse_qs(parsed.query) == {
        "stationDn": ["NE=33812827"],
        "timeDim": ["2"],
        "queryTime": [
            str(
                int(
                    datetime(
                        2026, 7, 20, tzinfo=ZoneInfo("Asia/Tokyo")
                    ).timestamp()
                    * 1000
                )
            )
        ],
        "timeZone": ["9"],
        "timeZoneStr": ["Asia/Tokyo"],
        "dateStr": ["2026-07-20 00:00:00"],
        "_": [str(int(request_time.timestamp() * 1000))],
    }
    assert result.source == "fusionsolar_energy_balance"
    assert result.timestamp is collected_at
    assert result.target_date == date(2026, 7, 20)
    assert result.payload is api_response
    assert set(result.payload) == {"success", "data", "failCode"}
    assert len(result.payload["data"]["xAxis"]) == 288
    assert result.payload["data"]["xAxis"] is x_axis
    for name in series_names:
        assert len(result.payload["data"][name]) == 288
        assert result.payload["data"][name] is series[name]
        assert result.payload["data"][name][-1] == "--"


def test_collect_range_includes_dates_in_order() -> None:
    collector = FusionSolarEnergyBalanceCollector(Mock())
    results = [Mock(), Mock(), Mock()]
    collector.collect_for_date = Mock(side_effect=results)

    assert collector.collect_range(
        date(2026, 7, 20), date(2026, 7, 22)
    ) == results
    assert collector.collect_for_date.call_args_list == [
        call(date(2026, 7, 20)),
        call(date(2026, 7, 21)),
        call(date(2026, 7, 22)),
    ]


def test_collect_range_rejects_reverse_range() -> None:
    collector = FusionSolarEnergyBalanceCollector(Mock())

    with pytest.raises(ValueError):
        collector.collect_range(date(2026, 7, 21), date(2026, 7, 20))
