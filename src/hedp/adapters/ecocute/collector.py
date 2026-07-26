"""Read-only EcoCute collection using advertised ECHONET Lite properties."""

from __future__ import annotations

from datetime import datetime, timezone
import secrets
from typing import Callable

from hedp.observations import ObservationTime
from hedp.storage import RawData

from .echonet import (
    PROPERTY_MAP_EPCS,
    FrameError,
    confirmed_property_name,
    decode_property_maps,
)
from .state import normalize_observation
from .transport import EcoCuteReadOnlyUdpTransport


CONFIRMED_STATE_EPCS = frozenset(
    (0x80, 0x86, 0x88, 0x89, 0xB0, 0xB2, 0xC3, 0xD1, 0xD3, 0xE1, 0xEA)
)


class EcoCuteReadOnlyCollector:
    source = "ecocute_echonet_lite"

    def __init__(
        self,
        transport: EcoCuteReadOnlyUdpTransport,
        *,
        target_alias: str,
        instance_code: int = 1,
        transaction_id_factory: Callable[[], int] = (
            lambda: secrets.randbelow(0x10000)
        ),
    ) -> None:
        if not target_alias:
            raise ValueError("target_alias must not be empty")
        if not 1 <= instance_code <= 0xFF:
            raise ValueError("instance_code must be between 1 and 255")
        self.transport = transport
        self.target_alias = target_alias
        self.instance_code = instance_code
        self._transaction_id_factory = transaction_id_factory

    def collect(self) -> RawData:
        map_exchange = self.transport.get(
            transaction_id=self._transaction_id(),
            epcs=tuple(sorted(PROPERTY_MAP_EPCS)),
            instance_code=self.instance_code,
        )
        maps = decode_property_maps(map_exchange.frame)
        if maps.get is None:
            raise FrameError("EcoCute Get property map is missing")
        requested = tuple(
            sorted(CONFIRMED_STATE_EPCS & maps.get.properties)
        )
        if not requested:
            raise FrameError("EcoCute advertises no confirmed state properties")

        state_exchange = self.transport.get(
            transaction_id=self._transaction_id(),
            epcs=requested,
            instance_code=self.instance_code,
        )
        received_at = datetime.now(timezone.utc)
        time = ObservationTime(
            received_at.isoformat(),
            received_at.isoformat(),
        )
        observation = normalize_observation(state_exchange.frame, time=time)
        return RawData(
            source=self.source,
            timestamp=received_at,
            payload={
                "property_map_response_hex": map_exchange.response.hex(),
                "state_response_hex": state_exchange.response.hex(),
                "advertised": {
                    "inf": _properties(maps.inf),
                    "set": _properties(maps.set),
                    "get": _properties(maps.get),
                },
                "requested_epcs": list(requested),
                "properties": [
                    {
                        "epc": item.epc,
                        "name": confirmed_property_name(item.epc),
                        "value": item.reading.value,
                        "quality": item.reading.quality.value,
                        "reason": item.reading.reason,
                    }
                    for item in observation.properties
                ],
            },
            metadata={
                "target_alias": self.target_alias,
                "instance_code": self.instance_code,
                "observation_source": observation.source.value,
                "timestamp_basis": "collector_receipt",
            },
        )

    def _transaction_id(self) -> int:
        value = self._transaction_id_factory()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("transaction ID factory must return an integer")
        if not 0 <= value <= 0xFFFF:
            raise ValueError("transaction ID factory returned an invalid value")
        return value


def _properties(value: object) -> list[int] | None:
    properties = getattr(value, "properties", None)
    return sorted(properties) if isinstance(properties, frozenset) else None
