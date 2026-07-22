from urllib.parse import parse_qs, urlsplit

from hedp.adapters.fusionsolar.device_realtime_collector import FusionSolarDeviceRealtimeCollector


class Client:
    station_dn = "station"

    def __init__(self):
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return {"data": {"signals": ["--", "-", None, []]}}


def test_collect_device_preserves_payload_and_identity():
    client = Client()
    collector = FusionSolarDeviceRealtimeCollector(client)
    raw = collector.collect_device("NE=1")
    parts = urlsplit(client.urls[0])
    query = parse_qs(parts.query)
    assert parts.path == collector.ENDPOINT
    assert query["deviceDn"] == ["NE=1"]
    assert "_" in query
    assert raw.payload["data"]["signals"] == ["--", "-", None, []]
    assert raw.metadata == {"device_dn": "NE=1"}
    assert raw.timestamp.utcoffset().total_seconds() == 0


def test_collect_devices_continues_after_failure():
    client = Client()
    collector = FusionSolarDeviceRealtimeCollector(client)
    original = collector.collect_device

    def collect(device_dn):
        if device_dn == "bad":
            raise RuntimeError("failed")
        return original(device_dn)

    collector.collect_device = collect
    collected, failures = collector.collect_devices(["bad", "good"])
    assert len(collected) == 1
    assert failures[0][0] == "bad"
