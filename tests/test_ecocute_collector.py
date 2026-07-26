from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.ecocute import (
    EchonetExchange,
    EcoCuteReadOnlyCollector,
    FrameError,
    parse_frame,
)
from hedp.adapters.read_only_qualification import (
    ReadOnlyOfflineQualificationChecker,
)


FIXTURE = Path(__file__).parent / "fixtures/ecocute/property_maps_v1.json"
STATE = bytes.fromhex("10810002026b0105ff017202800130e102012c")


class FakeTransport:
    def __init__(self, property_map: bytes) -> None:
        self.property_map = property_map
        self.requests: list[tuple[int, ...]] = []

    def get(
        self,
        *,
        transaction_id: int,
        epcs: tuple[int, ...],
        instance_code: int = 1,
    ) -> EchonetExchange:
        self.requests.append(epcs)
        raw = self.property_map if len(self.requests) == 1 else STATE
        return EchonetExchange(b"request", raw, parse_frame(raw))


def test_collector_reads_maps_first_and_preserves_complete_raw() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    map_raw = bytes.fromhex(fixture["packet_hex"])
    transport = FakeTransport(map_raw)
    transactions = iter((1, 2))
    collector = EcoCuteReadOnlyCollector(
        transport,  # type: ignore[arg-type]
        target_alias="ecocute_main",
        transaction_id_factory=lambda: next(transactions),
    )

    raw = collector.collect()

    assert transport.requests[0] == (0x9D, 0x9E, 0x9F)
    assert all(len(batch) <= 4 for batch in transport.requests)
    requested = tuple(epc for batch in transport.requests[1:] for epc in batch)
    assert requested == tuple(sorted(set(requested)))
    assert {0xC0, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xE3} <= set(requested)
    assert raw.source == "ecocute_echonet_lite"
    assert raw.payload["property_map_response_hex"] == map_raw.hex()
    assert raw.payload["state_response_hex"] == [STATE.hex()] * (
        len(transport.requests) - 1
    )
    assert raw.metadata["partial_property_count"] > 0
    assert raw.metadata["target_alias"] == "ecocute_main"
    assert "host" not in raw.metadata
    qualification = ReadOnlyOfflineQualificationChecker().evaluate(raw)
    assert qualification.status == "qualified"
    assert qualification.evidence_count == len(raw.payload["state_response_hex"]) + 1


def test_collector_rejects_a_response_without_get_map() -> None:
    raw = bytes.fromhex("10810001026b0105ff017201800130")
    collector = EcoCuteReadOnlyCollector(
        FakeTransport(raw),  # type: ignore[arg-type]
        target_alias="ecocute_main",
        transaction_id_factory=lambda: 1,
    )

    with pytest.raises(FrameError, match="Get property map"):
        collector.collect()
