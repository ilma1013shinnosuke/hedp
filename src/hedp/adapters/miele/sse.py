"""Bounded, transport-independent Server-Sent Events parsing."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
import json


@dataclass(frozen=True)
class SseEvent:
    name: str
    payload: Mapping[str, object] = field(repr=False)


def parse_sse(
    lines: Iterable[str | bytes],
    *,
    max_event_bytes: int = 256 * 1024,
    max_data_lines: int = 512,
) -> Iterator[SseEvent]:
    """Parse one finite transcript without reconnecting or accessing a URL."""

    if max_event_bytes <= 0 or max_data_lines <= 0:
        raise ValueError("SSE limits must be positive")
    event_name = "message"
    data_lines: list[str] = []
    event_bytes = 0

    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8")
        elif isinstance(raw_line, str):
            line = raw_line
        else:
            raise TypeError("SSE lines must be strings or bytes")
        if line == "":
            if data_lines:
                yield _event(event_name, data_lines)
            event_name = "message"
            data_lines = []
            event_bytes = 0
            continue
        if line.startswith(":"):
            continue
        field_name, separator, value = line.partition(":")
        if not separator:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field_name == "event":
            event_name = value
        elif field_name == "data":
            data_lines.append(value)
            event_bytes += len(value.encode("utf-8"))
            if len(data_lines) > max_data_lines:
                raise ValueError("SSE event exceeds data-line limit")
            if event_bytes > max_event_bytes:
                raise ValueError("SSE event exceeds byte limit")
    if data_lines:
        yield _event(event_name, data_lines)


def _event(name: str, data_lines: list[str]) -> SseEvent:
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise ValueError("Miele SSE data is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Miele SSE data is not a JSON object")
    return SseEvent(name, payload)
