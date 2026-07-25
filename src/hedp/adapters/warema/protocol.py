from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FrameError(ValueError):
    """WMS USB frameの構造が不正。"""


@dataclass(frozen=True)
class Frame:
    kind: str
    command_type: str | None = None
    payload: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


def _hex(value: str, length: int, label: str) -> str:
    normalized = value.upper()
    if len(normalized) != length or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        raise FrameError(f"{label} must be {length} hexadecimal characters")
    return normalized


def _height(value: str) -> int | None:
    normalized = _hex(value, 2, "height")
    return None if normalized == "FF" else round(int(normalized, 16) / 2)


def _angle(value: str) -> int | None:
    normalized = _hex(value, 2, "angle")
    if normalized == "FF":
        return None
    return round((int(normalized, 16) - 127) / 75 * 100)


def decode_frame(raw: bytes | str) -> Frame:
    try:
        text = raw.decode("ascii") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError as error:
        raise FrameError("frame must be ASCII") from error
    if not isinstance(text, str):
        raise TypeError("raw must be bytes or str")
    if len(text) > 8_192:
        raise FrameError("frame length limit exceeded")
    if not text.startswith("{") or not text.endswith("}"):
        raise FrameError("frame boundary missing")

    if text == "{a}":
        return Frame("ack")
    if text == "{f}":
        return Frame("forward")
    if text.startswith("{g"):
        return Frame("stick_name", fields={"value": text[2:-1]})
    if text.startswith("{v"):
        return Frame("stick_version", fields={"value": text[2:-1]})
    if not text.startswith("{r"):
        return Frame("unknown")
    if len(text) < 13:
        raise FrameError("radio frame too short")

    command_type = _hex(text[8:12], 4, "command_type")
    payload = text[12:-1].upper()
    if command_type == "8011" and payload.startswith(("01000003", "01000005")):
        if len(payload) < 18:
            raise FrameError("state payload too short")
        return Frame(
            "state",
            command_type,
            payload,
            {
                "height_raw_percent": _height(payload[8:10]),
                "angle_raw_percent": _angle(payload[10:12]),
                "moving": payload[16:18] != "00",
                "unknown_tail": payload[18:],
            },
        )
    if command_type == "7070":
        if len(payload) < 6:
            raise FrameError("movement payload too short")
        return Frame(
            "movement",
            command_type,
            payload,
            {
                "height_raw_percent": _height(payload[2:4]),
                "angle_raw_percent": _angle(payload[4:6]),
                "unknown_tail": payload[6:],
            },
        )
    if command_type == "7021":
        if len(payload) < 6:
            raise FrameError("scan payload too short")
        return Frame(
            "scan_response",
            command_type,
            payload,
            {"device_type": payload[4:6], "unknown_tail": payload[6:]},
        )
    if command_type == "5018":
        return Frame("restricted_join_network", command_type)
    if command_type == "7071":
        return Frame("movement_response", command_type)
    return Frame("unknown_radio", command_type)


class FrameStream:
    def __init__(self, *, max_buffer: int = 8_192) -> None:
        if max_buffer <= 0:
            raise ValueError("max_buffer must be positive")
        self._buffer = bytearray()
        self._max_buffer = max_buffer

    def feed(self, chunk: bytes) -> tuple[Frame, ...]:
        if not isinstance(chunk, bytes):
            raise TypeError("chunk must be bytes")
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_buffer:
            self._buffer.clear()
            raise FrameError("stream buffer limit exceeded")

        frames: list[Frame] = []
        while b"}" in self._buffer:
            end = self._buffer.index(ord("}"))
            candidate = bytes(self._buffer[: end + 1])
            del self._buffer[: end + 1]
            start = candidate.find(b"{")
            if start >= 0:
                frames.append(decode_frame(candidate[start:]))
        return tuple(frames)
