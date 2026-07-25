from __future__ import annotations

from dataclasses import dataclass


START = 0xCC
END = 0xAA
FRAGMENTED = 0x80
NOTIFICATION = 0x40
REQUEST_ID_MASK = 0x3F
SHORT_LIMIT = 65_501
FRAGMENT_SIZE = 65_493


class FrameError(ValueError):
    """Smart LEDZ frameの構造が不正。"""


@dataclass(frozen=True)
class Frame:
    request_id: int
    payload: bytes
    notification: bool = False
    fragment_index: int = 0
    fragment_count: int = 1
    total_length: int | None = None

    @property
    def fragmented(self) -> bool:
        return self.fragment_count > 1


def encode_frames(
    payload: bytes, *, request_id: int, notification: bool = False
) -> tuple[bytes, ...]:
    if isinstance(request_id, bool) or not isinstance(request_id, int):
        raise TypeError("request_id must be an integer")
    if not 0 <= request_id <= REQUEST_ID_MASK:
        raise ValueError("request_id must be between 0 and 63")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    flags = request_id | (NOTIFICATION if notification else 0)
    if len(payload) < SHORT_LIMIT:
        return (
            bytes((START, flags))
            + len(payload).to_bytes(2, "big")
            + payload
            + bytes((END,)),
        )

    chunks = tuple(
        payload[offset : offset + FRAGMENT_SIZE]
        for offset in range(0, len(payload), FRAGMENT_SIZE)
    )
    if len(chunks) > 255:
        raise ValueError("payload requires more than 255 fragments")
    return tuple(
        bytes((START, flags | FRAGMENTED, index, len(chunks)))
        + len(payload).to_bytes(4, "big")
        + chunk
        + bytes((END,))
        for index, chunk in enumerate(chunks)
    )


def decode_frame(raw: bytes) -> Frame:
    if len(raw) < 5:
        raise FrameError("frame is too short")
    if raw[0] != START or raw[-1] != END:
        raise FrameError("invalid frame boundary")

    flags = raw[1]
    request_id = flags & REQUEST_ID_MASK
    notification = bool(flags & NOTIFICATION)
    if flags & FRAGMENTED:
        if len(raw) < 9:
            raise FrameError("fragmented frame is too short")
        index, count = raw[2], raw[3]
        total_length = int.from_bytes(raw[4:8], "big")
        payload = raw[8:-1]
        if count == 0 or index >= count:
            raise FrameError("invalid fragment position")
        if total_length <= 0 or len(payload) > FRAGMENT_SIZE:
            raise FrameError("invalid fragmented payload length")
        return Frame(
            request_id=request_id,
            payload=payload,
            notification=notification,
            fragment_index=index,
            fragment_count=count,
            total_length=total_length,
        )

    declared_length = int.from_bytes(raw[2:4], "big")
    payload = raw[4:-1]
    if len(payload) != declared_length:
        raise FrameError("short-frame payload length mismatch")
    return Frame(request_id, payload, notification)


def reassemble(frames: tuple[Frame, ...] | list[Frame]) -> bytes:
    if not frames:
        raise FrameError("no frames to reassemble")
    first = frames[0]
    if len(frames) == 1 and not first.fragmented:
        return first.payload
    if any(not frame.fragmented for frame in frames):
        raise FrameError("mixed short and fragmented frames")
    if any(frame.request_id != first.request_id for frame in frames):
        raise FrameError("fragment request IDs differ")
    if any(frame.notification != first.notification for frame in frames):
        raise FrameError("fragment notification flags differ")
    if any(frame.fragment_count != first.fragment_count for frame in frames):
        raise FrameError("fragment counts differ")
    if any(frame.total_length != first.total_length for frame in frames):
        raise FrameError("fragment total lengths differ")
    if len(frames) != first.fragment_count:
        raise FrameError("fragment set is incomplete")

    ordered = sorted(frames, key=lambda frame: frame.fragment_index)
    if [frame.fragment_index for frame in ordered] != list(range(len(ordered))):
        raise FrameError("fragment indexes are incomplete or duplicated")
    payload = b"".join(frame.payload for frame in ordered)
    if len(payload) != first.total_length:
        raise FrameError("reassembled payload length mismatch")
    return payload
