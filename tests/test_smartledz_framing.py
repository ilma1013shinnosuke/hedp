import pytest

from hedp.adapters.smartledz.framing import (
    FRAGMENT_SIZE,
    SHORT_LIMIT,
    FrameError,
    decode_frame,
    encode_frames,
    reassemble,
)


def test_short_frame_round_trip() -> None:
    payload = b'{"c":"SystemInfo"}'
    encoded = encode_frames(payload, request_id=7)

    assert len(encoded) == 1
    frame = decode_frame(encoded[0])
    assert frame.request_id == 7
    assert not frame.notification
    assert reassemble([frame]) == payload


def test_notification_flag_is_preserved() -> None:
    frame = decode_frame(
        encode_frames(b'{"event":"changed"}', request_id=2, notification=True)[0]
    )

    assert frame.notification
    assert frame.request_id == 2


def test_fragmented_round_trip() -> None:
    payload = b"x" * (FRAGMENT_SIZE + 19)
    encoded = encode_frames(payload, request_id=63)
    frames = [decode_frame(item) for item in reversed(encoded)]

    assert len(frames) == 2
    assert reassemble(frames) == payload


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xcc\x00\x00\x00\x00",
        b"\x00\x00\x00\x00\xaa",
        b"\xcc\x00\x00\x02x\xaa",
    ],
)
def test_invalid_frames_are_rejected(raw: bytes) -> None:
    with pytest.raises(FrameError):
        decode_frame(raw)


def test_incomplete_fragment_set_is_rejected() -> None:
    payload = b"x" * (SHORT_LIMIT + 1)
    frame = decode_frame(encode_frames(payload, request_id=1)[0])

    with pytest.raises(FrameError, match="incomplete"):
        reassemble([frame])
