from datetime import date

from hedp.fusionsolar_alarm_collector import FusionSolarAlarmCollector


class Client:
    def __init__(self, totals=None):
        self.calls = []
        self.totals = iter(totals or [0])

    def post_json(self, path, payload):
        self.calls.append((path, payload))
        return {
            "success": True,
            "data": {
                "offset": 0,
                "limit": 10,
                "totalCount": next(self.totals),
                "sizeExceeded": False,
                "groupResult": None,
                "severityStatistics": [],
                "hits": [],
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


def test_collect_history_builds_tokyo_range_and_paginates():
    client = Client([11, 11])
    collector = FusionSolarAlarmCollector(client)

    results = collector.collect_history_device(
        "NE=1", date(2026, 7, 19), date(2026, 7, 20)
    )

    assert len(results) == 2
    first = client.calls[0][1]
    assert first["dataType"] == "HISTORY"
    assert first["occurUTC"] == {
        "begin": 1784386800000,
        "end": 1784559599000,
    }
    assert client.calls[1][1]["pageNo"] == 2
    assert results[0].metadata["start_date"] == "2026-07-19"
    assert results[0].metadata["end_date"] == "2026-07-20"


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
