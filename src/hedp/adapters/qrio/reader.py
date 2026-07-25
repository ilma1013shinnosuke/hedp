"""OS-independent read port for Qrio transport implementations."""

from __future__ import annotations

from typing import Protocol


class QrioReadPort(Protocol):
    """Transport contract; implementations own credentials and HTTP details."""

    def status(self, source_lock_id: str) -> object: ...

    def health(self) -> object: ...

    def history(self, source_lock_id: str, *, page: int) -> object: ...


class QrioReader:
    """Read-only facade that cannot expose lock/unlock operations."""

    def __init__(self, transport: QrioReadPort) -> None:
        self._transport = transport

    def status(self, source_lock_id: str) -> object:
        return self._transport.status(source_lock_id)

    def health(self) -> object:
        return self._transport.health()

    def history(self, source_lock_id: str, *, page: int = 1) -> object:
        if page < 1:
            raise ValueError("page must be positive")
        return self._transport.history(source_lock_id, page=page)
