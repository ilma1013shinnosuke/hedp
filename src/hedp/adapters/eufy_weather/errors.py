"""Fixed-vocabulary errors for camera snapshot acquisition."""

from __future__ import annotations


class SnapshotError(RuntimeError):
    """A camera read failure whose message never contains an upstream URL."""

    code = "snapshot_error"
    retryable = False

    def __init__(self) -> None:
        super().__init__(self.code)


class SnapshotBackendUnavailable(SnapshotError):
    code = "snapshot_backend_unavailable"


class SnapshotTimeout(SnapshotError):
    code = "snapshot_timeout"
    retryable = True


class SnapshotUnavailable(SnapshotError):
    code = "snapshot_unavailable"
    retryable = True
