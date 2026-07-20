from urllib.parse import parse_qs, urlsplit

from hedp.fusionsolar_battery_dc_collector import (
    FusionSolarBatteryDcCollector,
)


class Client:
    def __init__(self):
        self.urls = []
        self.payload = {
            "success": True,
            "data": [{"id": 1, "value": "--", "realValue": None}],
        }

    def get_json(self, url):
        self.urls.append(url)
        return self.payload


def test_collect_module_uses_confirmed_request_and_preserves_payload():
    client = Client()
    collector = FusionSolarBatteryDcCollector(client)

    raw_data = collector.collect_module("NE=1", "1,2", 3)

    parts = urlsplit(client.urls[0])
    query = parse_qs(parts.query)
    assert parts.path == collector.ENDPOINT
    assert query["dn"] == ["NE=1"]
    assert query["sigids"] == ["1,2"]
    assert query["moduleId"] == ["3"]
    assert "_" in query
    assert raw_data.payload is client.payload
    assert raw_data.metadata == {"device_dn": "NE=1", "module_id": 3}
    assert raw_data.source == "fusionsolar_battery_dc"
    assert raw_data.timestamp.utcoffset().total_seconds() == 0


def test_collect_modules_continues_after_failure():
    client = Client()
    collector = FusionSolarBatteryDcCollector(client)
    original = collector.collect_module

    def collect(device_dn, sigids, module_id):
        if module_id == 2:
            raise RuntimeError("failed")
        return original(device_dn, sigids, module_id)

    collector.collect_module = collect
    collected, failures = collector.collect_modules("NE=1", "1", [1, 2, 3])

    assert [item.metadata["module_id"] for item in collected] == [1, 3]
    assert failures[0][0] == 2
