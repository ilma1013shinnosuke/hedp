"""Bounded TCP transport for confirmed Smart LEDZ read commands only."""

from __future__ import annotations

from collections.abc import Callable
import json
import socket

from .framing import END, FRAGMENTED, FRAGMENT_SIZE, Frame, decode_frame, encode_frames, reassemble
from .read_commands import ReadCommand


class SmartLedzTransportError(RuntimeError):
    """A privacy-safe read failure that never includes addresses or payloads."""


class SmartLedzTcpReadTransport:
    """Send only ``ReadCommand`` values over a bounded TCP connection."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_seconds: float = 5.0,
        connect: Callable[..., socket.socket] = socket.create_connection,
    ) -> None:
        if not host:
            raise ValueError("host must not be empty")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        self._address = (host, port)
        self._timeout = timeout_seconds
        self._connect = connect
        self._next_request_id = 0

    def read(self, command: ReadCommand) -> object:
        if not isinstance(command, ReadCommand):
            raise TypeError("command must be a confirmed ReadCommand")
        request_id = self._next_request_id
        self._next_request_id = (request_id + 1) % 64
        payload = json.dumps(
            command.payload(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        try:
            with self._connect(self._address, self._timeout) as connection:
                connection.settimeout(self._timeout)
                for frame in encode_frames(payload, request_id=request_id):
                    connection.sendall(frame)
                frames = self._receive_response(connection, request_id)
        except OSError as error:
            raise SmartLedzTransportError("Smart LEDZ read request failed") from error
        try:
            decoded = json.loads(reassemble(frames).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SmartLedzTransportError(
                "Smart LEDZ response is invalid JSON"
            ) from error
        if not isinstance(decoded, dict):
            raise SmartLedzTransportError(
                "Smart LEDZ response must be a JSON object"
            )
        return decoded

    @staticmethod
    def _receive_response(connection: socket.socket, request_id: int) -> list[Frame]:
        frames: list[Frame] = []
        expected_count = 1
        while len(frames) < expected_count:
            prefix = _receive_exact(connection, 2)
            if prefix[1] & FRAGMENTED:
                header = prefix + _receive_exact(connection, 6)
                index, count = header[2], header[3]
                total_length = int.from_bytes(header[4:8], "big")
                payload_length = min(
                    FRAGMENT_SIZE, total_length - index * FRAGMENT_SIZE
                )
                raw = header + _receive_exact(connection, payload_length + 1)
                expected_count = count
            else:
                length_bytes = _receive_exact(connection, 2)
                payload_length = int.from_bytes(length_bytes, "big")
                raw = prefix + length_bytes + _receive_exact(
                    connection, payload_length + 1
                )
            frame = decode_frame(raw)
            if frame.notification or frame.request_id != request_id:
                raise ValueError("Smart LEDZ response correlation failed")
            if raw[-1] != END:
                raise ValueError("Smart LEDZ response terminator is invalid")
            frames.append(frame)
        return frames


def _receive_exact(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise ConnectionError("Smart LEDZ connection closed before response")
        chunks.extend(chunk)
    return bytes(chunks)
