"""Fast real-time delivery separated from bounded asynchronous work.

Publishing an event calls only registered real-time consumers.  Persistence,
aggregation, Raw transfer, and audit are represented by separate bounded
queues and are never executed on the publish path.
"""

from __future__ import annotations

import math
import re
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")
_EVENT_MEMORY_LIMIT = 4096


@dataclass(frozen=True)
class EventEnvelope(Generic[T]):
    """One ordered, deduplicated observation or event."""

    source_alias: str
    event_id: str
    sequence: int
    observed_at: datetime
    payload: T
    important: bool = False

    def __post_init__(self) -> None:
        _name("source_alias", self.source_alias)
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a non-empty string")
        if len(self.event_id) > 256:
            raise ValueError("event_id must be at most 256 characters")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.important, bool):
            raise TypeError("important must be a boolean")


class DeliveryStatus(str, Enum):
    DELIVERED = "delivered"
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    TIMEOUT = "timeout"
    FAILED = "failed"
    BACKPRESSURE = "backpressure"
    RETRY_QUEUED = "retry_queued"
    RETRIES_EXHAUSTED = "retries_exhausted"
    EMPTY = "empty"


@dataclass(frozen=True)
class DeliveryReceipt:
    """Sanitized outcome for one consumer or asynchronous lane."""

    target: str
    status: DeliveryStatus
    event_id: str
    attempt: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class _QueuedEvent(Generic[T]):
    event: EventEnvelope[T]
    attempt: int = 0


class AsyncDeliveryQueue(Generic[T]):
    """Bounded lane drained by a background worker outside the publish path."""

    def __init__(self, name: str, *, capacity: int, max_attempts: int = 3) -> None:
        _name("name", name)
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an integer")
        if capacity < 1:
            raise ValueError("capacity must be positive")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise TypeError("max_attempts must be an integer")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        self.name = name
        self._capacity = capacity
        self._max_attempts = max_attempts
        self._items: deque[_QueuedEvent[T]] = deque()
        self._lock = Lock()

    def enqueue(self, event: EventEnvelope[T]) -> DeliveryReceipt:
        with self._lock:
            if len(self._items) >= self._capacity:
                return DeliveryReceipt(
                    self.name,
                    DeliveryStatus.BACKPRESSURE,
                    event.event_id,
                    reason="async_lane_capacity_reached",
                )
            self._items.append(_QueuedEvent(event))
        return DeliveryReceipt(self.name, DeliveryStatus.QUEUED, event.event_id)

    def deliver_one(
        self, sink: Callable[[EventEnvelope[T]], None]
    ) -> DeliveryReceipt:
        """Deliver one item; bounded retry stays in this asynchronous lane."""

        with self._lock:
            if not self._items:
                return DeliveryReceipt(self.name, DeliveryStatus.EMPTY, "")
            queued = self._items.popleft()
        attempt = queued.attempt + 1
        try:
            sink(queued.event)
        except Exception:
            if attempt < self._max_attempts:
                with self._lock:
                    self._items.appendleft(_QueuedEvent(queued.event, attempt))
                return DeliveryReceipt(
                    self.name,
                    DeliveryStatus.RETRY_QUEUED,
                    queued.event.event_id,
                    attempt,
                    "async_sink_failed",
                )
            return DeliveryReceipt(
                self.name,
                DeliveryStatus.RETRIES_EXHAUSTED,
                queued.event.event_id,
                attempt,
                "async_sink_failed",
            )
        return DeliveryReceipt(
            self.name,
            DeliveryStatus.DELIVERED,
            queued.event.event_id,
            attempt,
        )

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class EventDeliveryHub(Generic[T]):
    """Process-local first hop with control-first delivery and explicit failure."""

    def __init__(
        self,
        *,
        realtime_consumers: Mapping[str, Callable[[EventEnvelope[T]], None]],
        async_lanes: Mapping[str, AsyncDeliveryQueue[T]],
        realtime_timeout_seconds: float = 0.25,
    ) -> None:
        if not realtime_consumers:
            raise ValueError("at least one realtime consumer is required")
        for name in realtime_consumers:
            _name("realtime consumer name", name)
        for name, lane in async_lanes.items():
            _name("async lane name", name)
            if lane.name != name:
                raise ValueError("async lane mapping key must equal lane name")
        if (
            isinstance(realtime_timeout_seconds, bool)
            or not isinstance(realtime_timeout_seconds, (int, float))
            or not math.isfinite(realtime_timeout_seconds)
            or realtime_timeout_seconds <= 0
            or realtime_timeout_seconds > 30
        ):
            raise ValueError(
                "realtime_timeout_seconds must be greater than 0 and at most 30"
            )
        self._realtime_consumers = dict(realtime_consumers)
        self._async_lanes = dict(async_lanes)
        self._timeout = float(realtime_timeout_seconds)
        self._executor = ThreadPoolExecutor(
            max_workers=len(realtime_consumers),
            thread_name_prefix="hestia-event",
        )
        self._lock = Lock()
        self._last_sequence: dict[str, int] = {}
        self._seen_ids: set[tuple[str, str]] = set()
        self._seen_order: deque[tuple[str, str]] = deque()

    def publish(self, event: EventEnvelope[T]) -> tuple[DeliveryReceipt, ...]:
        """Deliver control consumers first, then only enqueue background work."""

        rejected = self._claim(event)
        if rejected is not None:
            return (rejected,)

        futures = {
            self._executor.submit(consumer, event): name
            for name, consumer in self._realtime_consumers.items()
        }
        done, pending = wait(futures, timeout=self._timeout)
        receipts: list[DeliveryReceipt] = []
        for future, name in futures.items():
            if future in pending:
                future.cancel()
                receipts.append(
                    DeliveryReceipt(
                        name,
                        DeliveryStatus.TIMEOUT,
                        event.event_id,
                        1,
                        "realtime_consumer_timeout_result_unknown",
                    )
                )
                continue
            try:
                future.result()
            except Exception:
                receipts.append(
                    DeliveryReceipt(
                        name,
                        DeliveryStatus.FAILED,
                        event.event_id,
                        1,
                        "realtime_consumer_failed",
                    )
                )
            else:
                receipts.append(
                    DeliveryReceipt(
                        name, DeliveryStatus.DELIVERED, event.event_id, 1
                    )
                )

        # Queues are touched only after the real-time route has completed.
        # Their sinks are never called here, so storage failure cannot delay
        # or prevent the control decision above.
        for lane in self._async_lanes.values():
            receipts.append(lane.enqueue(event))
        return tuple(receipts)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> EventDeliveryHub[T]:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _claim(self, event: EventEnvelope[T]) -> DeliveryReceipt | None:
        key = (event.source_alias, event.event_id)
        with self._lock:
            if key in self._seen_ids:
                return DeliveryReceipt(
                    "event-hub", DeliveryStatus.DUPLICATE, event.event_id
                )
            previous = self._last_sequence.get(event.source_alias)
            if previous is not None and event.sequence <= previous:
                return DeliveryReceipt(
                    "event-hub",
                    DeliveryStatus.OUT_OF_ORDER,
                    event.event_id,
                    reason="source_sequence_not_increasing",
                )
            self._last_sequence[event.source_alias] = event.sequence
            self._seen_ids.add(key)
            self._seen_order.append(key)
            while len(self._seen_order) > _EVENT_MEMORY_LIMIT:
                removed = self._seen_order.popleft()
                self._seen_ids.remove(removed)
        return None


def _name(label: str, value: str) -> None:
    if not isinstance(value, str) or _SAFE_NAME.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe name")
