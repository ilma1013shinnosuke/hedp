from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic

from hedp.events import (
    AsyncDeliveryQueue,
    DeliveryStatus,
    EventDeliveryHub,
    EventEnvelope,
)


def envelope(event_id: str = "event-1", sequence: int = 1) -> EventEnvelope[str]:
    return EventEnvelope(
        source_alias="source",
        event_id=event_id,
        sequence=sequence,
        observed_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        payload="payload",
        important=True,
    )


def test_realtime_delivery_precedes_asynchronous_sink_work() -> None:
    calls: list[str] = []
    storage = AsyncDeliveryQueue[str]("storage", capacity=2)
    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda _: calls.append("control")},
        async_lanes={"storage": storage},
    )
    receipts = hub.publish(envelope())

    assert calls == ["control"]
    assert [item.status for item in receipts] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]
    assert len(storage) == 1
    assert storage.deliver_one(lambda _: calls.append("storage")).status is (
        DeliveryStatus.DELIVERED
    )
    assert calls == ["control", "storage"]
    hub.close()


def test_full_async_lane_reports_backpressure_after_control_delivery() -> None:
    calls: list[str] = []
    storage = AsyncDeliveryQueue[str]("storage", capacity=1)
    storage.enqueue(envelope("already-queued", 0))
    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda _: calls.append("control")},
        async_lanes={"storage": storage},
    )

    receipts = hub.publish(envelope())
    assert calls == ["control"]
    assert receipts[-1].status is DeliveryStatus.BACKPRESSURE
    hub.close()


def test_duplicate_and_out_of_order_events_are_not_redelivered() -> None:
    calls: list[str] = []
    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda event: calls.append(event.event_id)},
        async_lanes={},
    )
    assert hub.publish(envelope("first", 2))[0].status is DeliveryStatus.DELIVERED
    assert hub.publish(envelope("first", 2))[0].status is DeliveryStatus.DUPLICATE
    assert (
        hub.publish(envelope("older", 1))[0].status is DeliveryStatus.OUT_OF_ORDER
    )
    assert calls == ["first"]
    hub.close()


def test_async_failure_retries_with_a_bound_and_preserves_head_order() -> None:
    storage = AsyncDeliveryQueue[str]("storage", capacity=2, max_attempts=2)
    storage.enqueue(envelope())
    assert storage.deliver_one(lambda _: 1 / 0).status is (
        DeliveryStatus.RETRY_QUEUED
    )
    exhausted = storage.deliver_one(lambda _: 1 / 0)
    assert exhausted.status is DeliveryStatus.RETRIES_EXHAUSTED
    assert exhausted.attempt == 2
    assert len(storage) == 0


def test_realtime_timeout_is_explicit_and_is_not_automatically_redispatched() -> None:
    release = Event()
    calls = 0

    def blocked(_: EventEnvelope[str]) -> None:
        nonlocal calls
        calls += 1
        release.wait(1)

    hub = EventDeliveryHub(
        realtime_consumers={"control": blocked},
        async_lanes={},
        realtime_timeout_seconds=0.01,
    )
    receipt = hub.publish(envelope())[0]
    release.set()

    assert receipt.status is DeliveryStatus.TIMEOUT
    assert receipt.reason == "realtime_consumer_timeout_result_unknown"
    assert calls == 1
    hub.close()


def test_slow_asynchronous_persistence_drain_does_not_delay_realtime_publish() -> None:
    """A blocked storage worker must never hold the control-first publish path."""

    storage = AsyncDeliveryQueue[str]("storage", capacity=2)
    assert storage.enqueue(envelope("stored-first", 0)).status is DeliveryStatus.QUEUED
    storage_started = Event()
    release_storage = Event()
    control_calls: list[str] = []

    def slow_storage(_: EventEnvelope[str]) -> None:
        storage_started.set()
        release_storage.wait(1)

    worker = Thread(target=lambda: storage.deliver_one(slow_storage))
    worker.start()
    assert storage_started.wait(0.5)

    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda event: control_calls.append(event.event_id)},
        async_lanes={"storage": storage},
        realtime_timeout_seconds=0.1,
    )
    started_at = monotonic()
    receipts = hub.publish(envelope("realtime-during-storage-delay", 1))
    elapsed = monotonic() - started_at

    release_storage.set()
    worker.join(timeout=1)
    hub.close()

    assert not worker.is_alive()
    assert elapsed < 0.2
    assert control_calls == ["realtime-during-storage-delay"]
    assert [receipt.status for receipt in receipts] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]


def test_kura_stub_failure_is_bounded_and_never_blocks_realtime_delivery() -> None:
    """KURA is an optional async lane: rejection is explicit, bounded, and isolated."""

    kura = AsyncDeliveryQueue[str]("kura", capacity=2, max_attempts=2)
    control_calls: list[str] = []
    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda event: control_calls.append(event.event_id)},
        async_lanes={"kura": kura},
    )

    first = hub.publish(envelope("kura-rejected", 1))
    retry = kura.deliver_one(lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    second = hub.publish(envelope("control-still-available", 2))
    exhausted = kura.deliver_one(
        lambda _: (_ for _ in ()).throw(RuntimeError("still-offline"))
    )
    hub.close()

    assert [receipt.status for receipt in first] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]
    assert retry.status is DeliveryStatus.RETRY_QUEUED
    assert retry.reason == "async_sink_failed"
    assert [receipt.status for receipt in second] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]
    assert exhausted.status is DeliveryStatus.RETRIES_EXHAUSTED
    assert control_calls == ["kura-rejected", "control-still-available"]


def test_slow_kura_stub_does_not_delay_realtime_delivery() -> None:
    """A stalled optional KURA drain is outside the real-time timeout budget."""

    kura = AsyncDeliveryQueue[str]("kura", capacity=2)
    assert kura.enqueue(envelope("kura-pending", 0)).status is DeliveryStatus.QUEUED
    kura_started = Event()
    release_kura = Event()
    control_calls: list[str] = []

    def stopped_kura(_: EventEnvelope[str]) -> None:
        kura_started.set()
        release_kura.wait(1)

    worker = Thread(target=lambda: kura.deliver_one(stopped_kura))
    worker.start()
    assert kura_started.wait(0.5)

    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda event: control_calls.append(event.event_id)},
        async_lanes={"kura": kura},
        realtime_timeout_seconds=0.1,
    )
    started_at = monotonic()
    receipts = hub.publish(envelope("control-during-kura-stall", 1))
    elapsed = monotonic() - started_at

    release_kura.set()
    worker.join(timeout=1)
    hub.close()

    assert not worker.is_alive()
    assert elapsed < 0.2
    assert control_calls == ["control-during-kura-stall"]
    assert [receipt.status for receipt in receipts] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.QUEUED,
    ]


def test_kura_stub_backpressure_does_not_delay_or_cancel_realtime_delivery() -> None:
    """A full optional KURA queue is a visible async failure, not a control failure."""

    kura = AsyncDeliveryQueue[str]("kura", capacity=1)
    assert kura.enqueue(envelope("kura-pending", 0)).status is DeliveryStatus.QUEUED
    control_calls: list[str] = []
    hub = EventDeliveryHub(
        realtime_consumers={"control": lambda event: control_calls.append(event.event_id)},
        async_lanes={"kura": kura},
        realtime_timeout_seconds=0.1,
    )

    started_at = monotonic()
    receipts = hub.publish(envelope("control-despite-kura-backpressure", 1))
    elapsed = monotonic() - started_at
    hub.close()

    assert elapsed < 0.2
    assert control_calls == ["control-despite-kura-backpressure"]
    assert [receipt.status for receipt in receipts] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.BACKPRESSURE,
    ]
    assert receipts[-1].reason == "async_lane_capacity_reached"
