"""OS-independent Miele REST/SSE read contract."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from .sse import SseEvent


class MieleReadPort(Protocol):
    """Credentials, HTTP and SSE connection ownership stay in transport."""

    def devices(self) -> object: ...

    def events(
        self,
        source_device_id: str,
        *,
        maximum_events: int,
        timeout_seconds: float,
    ) -> Iterator[SseEvent]:
        """Open one finite SSE connection; never reconnect."""
        ...


class MieleReader:
    """Read-only facade with no appliance action methods or retry loop."""

    def __init__(self, transport: MieleReadPort) -> None:
        self._transport = transport

    def devices(self) -> object:
        return self._transport.devices()

    def events(
        self,
        source_device_id: str,
        *,
        maximum_events: int,
        timeout_seconds: float,
    ) -> Iterator[SseEvent]:
        if not 1 <= maximum_events <= 1_024:
            raise ValueError("maximum_events must be between 1 and 1024")
        if not 0 < timeout_seconds <= 300:
            raise ValueError(
                "timeout_seconds must be greater than 0 and at most 300"
            )
        return self._transport.events(
            source_device_id,
            maximum_events=maximum_events,
            timeout_seconds=timeout_seconds,
        )
