from datetime import date

import pytest

from hedp.adapters.fusionsolar.alarm_collector import FusionSolarAlarmCollector


class Client:
    def __init__(self, totals=None):
        self.calls = []
        self.totals = iter(totals or [0])

    def post_json(self, path, payload):
        self.calls.append((path, payload))
        total_count = next(self.totals)
        return {
            "success": True,
            "data": {
                "offset": 0,
                "limit": 10,
                "totalCount": total_count,
                "sizeExceeded": False,
                "groupResult": None,
                "severityStatistics": [],
                "hits": (
                    [
                        {"alarmId": f"{payload['pageNo']}-{index}"}
                        for index in range(10)
                    ]
                    if total_count
                    else []
                ),
            },
        }


def test_collect_current_uses_confirmed_body_and_preserves_payload():
    client = Client()
    collector = FusionSolarAlarmCollector(client)

    raw_data = collector.collect_current_device("NE=1")[0]

    path, request = client.calls[0]
    assert path == collector.ENDPOINT
    assert request == {
        "dataType": "CURRENT",
        "domainType": "SOLAR",
        "pageNo": 1,
        "pageSize": 10,
        "nativeMoDn": ["NE=1"],
    }
    assert raw_data.payload["data"]["hits"] == []
    assert raw_data.source == "fusionsolar_alarm_current"
    assert raw_data.metadata["device_dn"] == "NE=1"
    assert raw_data.metadata["data_type"] == "CURRENT"
    assert raw_data.metadata["page_no"] == 1
    assert raw_data.metadata["page_size"] == 10
    assert raw_data.metadata["target_date"] is None
    assert raw_data.metadata["begin"] is None
    assert raw_data.metadata["end"] is None
    assert isinstance(raw_data.metadata["collection_id"], str)


def test_collect_history_builds_tokyo_range_and_paginates():
    client = Client([11, 11, 11, 11])
    collector = FusionSolarAlarmCollector(client)

    results = collector.collect_history_device(
        "NE=1", date(2026, 7, 19), date(2026, 7, 20)
    )

    assert len(results) == 4
    first = client.calls[0][1]
    assert first["dataType"] == "HISTORY"
    assert first["occurUTC"] == {
        "begin": 1784386800000,
        "end": 1784473199000,
    }
    assert client.calls[1][1]["pageNo"] == 2
    assert client.calls[2][1]["pageNo"] == 1
    assert client.calls[2][1]["occurUTC"] == {
        "begin": 1784473200000,
        "end": 1784559599000,
    }
    assert results[0].metadata["target_date"] == "2026-07-19"
    assert results[0].metadata["begin"] == 1784386800000
    assert results[0].metadata["end"] == 1784473199000


def test_pagination_rejects_repeated_page_content():
    class RepeatingClient:
        def post_json(self, path, payload):
            return {
                "success": True,
                "data": {"totalCount": 30, "hits": [{}] * 10},
            }

    collector = FusionSolarAlarmCollector(RepeatingClient())
    with pytest.raises(RuntimeError, match="repeated page"):
        collector.collect_current_device("NE=1")


def test_pagination_has_maximum_page_limit():
    client = Client([100_000] * 1001)
    collector = FusionSolarAlarmCollector(client, page_size=10)
    collector.MAX_PAGES = 2
    with pytest.raises(RuntimeError, match="maximum pages"):
        collector.collect_current_device("NE=1")


def test_collect_devices_continues_after_failure():
    collector = FusionSolarAlarmCollector(Client())
    original = collector.collect_current_device

    def collect(device_dn):
        if device_dn == "bad":
            raise RuntimeError("failed")
        return original(device_dn)

    collector.collect_current_device = collect
    collected, failures = collector.collect_current_devices(["bad", "good"])

    assert len(collected) == 1
    assert failures[0][0] == "bad"


def test_history_rejects_reverse_range():
    collector = FusionSolarAlarmCollector(Client())
    with pytest.raises(ValueError, match="start_date"):
        collector.collect_history_device(
            "NE=1", date(2026, 7, 20), date(2026, 7, 19)
        )
