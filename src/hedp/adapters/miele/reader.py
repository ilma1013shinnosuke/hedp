"""OS-independent Miele REST/SSE read contract."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from .sse import SseEvent


class MieleReadPort(Protocol):
    """Credentials, HTTP and SSE connection ownership stay in transport."""

    def devices(self) -> object: ...

    def events(self, source_device_id: str) -> Iterator[SseEvent]: ...


class MieleReader:
    """Read-only facade with no appliance action methods or retry loop."""

    def __init__(self, transport: MieleReadPort) -> None:
        self._transport = transport

    def devices(self) -> object:
        return self._transport.devices()

    def events(self, source_device_id: str) -> Iterator[SseEvent]:
        return self._transport.events(source_device_id)
