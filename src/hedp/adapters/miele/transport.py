"""Finite, read-only Miele REST/SSE transport."""

from __future__ import annotations

from collections.abc import Iterator
import json
from typing import Protocol
from urllib.parse import urlparse

import requests

from .sse import SseEvent, parse_sse


class MieleTransportError(RuntimeError):
    """A safe transport error that never includes credentials or response data."""


class _Response(Protocol):
    status_code: int
    content: bytes

    def iter_lines(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class _Session(Protocol):
    def get(self, url: str, **kwargs: object) -> _Response: ...


class MieleReadOnlyHttpTransport:
    """One-shot GET-only REST/SSE transport with no retries or actions."""

    def __init__(
        self,
        *,
        devices_url: str,
        events_url: str,
        access_token: str,
        rest_timeout_seconds: float = 15.0,
        maximum_rest_bytes: int = 2 * 1024 * 1024,
        session: _Session | None = None,
    ) -> None:
        _require_https_url("devices_url", devices_url)
        _require_https_url("events_url", events_url)
        if not access_token:
            raise ValueError("access_token must not be empty")
        if not 0 < rest_timeout_seconds <= 120:
            raise ValueError(
                "rest_timeout_seconds must be greater than 0 and at most 120"
            )
        if not 1 <= maximum_rest_bytes <= 16 * 1024 * 1024:
            raise ValueError("maximum_rest_bytes is out of range")
        self._devices_url = devices_url
        self._events_url = events_url
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        self._rest_timeout_seconds = rest_timeout_seconds
        self._maximum_rest_bytes = maximum_rest_bytes
        self._session = session or requests.Session()

    def devices(self) -> object:
        response = self._get(
            self._devices_url,
            accept="application/json",
            timeout_seconds=self._rest_timeout_seconds,
            stream=False,
        )
        try:
            content = response.content
            if len(content) > self._maximum_rest_bytes:
                raise MieleTransportError("Miele REST response exceeds byte limit")
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MieleTransportError("Miele REST response is invalid JSON") from error
        finally:
            response.close()
        if not isinstance(value, dict):
            raise MieleTransportError("Miele REST response must be an object")
        return value

    def events(
        self,
        source_device_id: str,
        *,
        maximum_events: int,
        timeout_seconds: float,
    ) -> Iterator[SseEvent]:
        if not source_device_id:
            raise ValueError("source_device_id must not be empty")
        if not 1 <= maximum_events <= 1_024:
            raise ValueError("maximum_events must be between 1 and 1024")
        if not 0 < timeout_seconds <= 300:
            raise ValueError(
                "timeout_seconds must be greater than 0 and at most 300"
            )
        response = self._get(
            self._events_url,
            accept="text/event-stream",
            timeout_seconds=timeout_seconds,
            stream=True,
        )
        try:
            for index, event in enumerate(parse_sse(response.iter_lines()), start=1):
                yield event
                if index >= maximum_events:
                    break
        except (requests.RequestException, UnicodeDecodeError) as error:
            raise MieleTransportError("Miele SSE connection failed") from error
        finally:
            response.close()

    def _get(
        self,
        url: str,
        *,
        accept: str,
        timeout_seconds: float,
        stream: bool,
    ) -> _Response:
        headers = dict(self._headers)
        headers["Accept"] = accept
        try:
            response = self._session.get(
                url,
                headers=headers,
                timeout=timeout_seconds,
                stream=stream,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise MieleTransportError("Miele read request failed") from error
        if response.status_code != 200:
            response.close()
            raise MieleTransportError("Miele read request was not accepted")
        return response


def _require_https_url(name: str, value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be an HTTPS URL without credentials or fragment")
