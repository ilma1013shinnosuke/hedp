import pytest

from hedp.adapters.warema.protocol import FrameError, FrameStream, decode_frame


def test_state_frame_is_normalized_without_identifier() -> None:
    frame = decode_frame("{r000000801101000005645EFFFF01}")

    assert frame.kind == "state"
    assert frame.fields["height_raw_percent"] == 50
    assert frame.fields["angle_raw_percent"] == -44
    assert frame.fields["moving"] is True
    assert "identifier" not in frame.fields


def test_missing_sentinel_is_not_zero() -> None:
    frame = decode_frame("{r000000801101000005FFFFFFFF00}")

    assert frame.fields["height_raw_percent"] is None
    assert frame.fields["angle_raw_percent"] is None


def test_join_network_body_is_never_exposed() -> None:
    frame = decode_frame("{r0000005018" + "0" * 40 + "}")

    assert frame.kind == "restricted_join_network"
    assert frame.payload == ""
    assert frame.fields == {}


def test_stream_handles_noise_and_split_frames() -> None:
    stream = FrameStream()

    assert stream.feed(b"noise{a") == ()
    assert [frame.kind for frame in stream.feed(b"}{v1.2}")] == [
        "ack",
        "stick_version",
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-a-frame",
        b"{r}",
        b"{r000000801101000005}",
        b"\xff}",
    ],
)
def test_invalid_frames_are_rejected(raw: bytes) -> None:
    with pytest.raises(FrameError):
        decode_frame(raw)


def test_stream_has_a_hard_limit() -> None:
    stream = FrameStream(max_buffer=8)

    with pytest.raises(FrameError, match="limit"):
        stream.feed(b"x" * 9)
