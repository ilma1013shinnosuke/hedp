"""Bounded HTTPS GET transport for configured Qrio read endpoints."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.error import URLError
from urllib.request import Request, urlopen


class QrioTransportError(RuntimeError):
    """A privacy-safe read failure that never includes URLs or response data."""


class QrioHttpsReadTransport:
    """Read-only transport whose three endpoint URLs are explicit configuration."""

    def __init__(
        self,
        *,
        status_url_template: str,
        health_url: str,
        history_url_template: str,
        authorization: str,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 1024 * 1024,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        for name, url in (
            ("status_url_template", status_url_template),
            ("health_url", health_url),
            ("history_url_template", history_url_template),
        ):
            _require_safe_https_url(name, url)
        if "{lock_id}" not in status_url_template:
            raise ValueError("status_url_template must contain {lock_id}")
        if "{lock_id}" not in history_url_template or "{page}" not in history_url_template:
            raise ValueError("history_url_template must contain {lock_id} and {page}")
        if not authorization:
            raise ValueError("authorization must not be empty")
        if "\r" in authorization or "\n" in authorization:
            raise ValueError("authorization must be a single header value")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if not 1 <= maximum_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("maximum_response_bytes is out of range")
        self._status_url = status_url_template
        self._health_url = health_url
        self._history_url = history_url_template
        self._authorization = authorization
        self._timeout = timeout_seconds
        self._maximum = maximum_response_bytes
        self._opener = opener

    def status(self, source_lock_id: str) -> object:
        return self._get(self._status_url.format(lock_id=quote(source_lock_id, safe="")))

    def health(self) -> object:
        return self._get(self._health_url)

    def history(self, source_lock_id: str, *, page: int) -> object:
        if page < 1:
            raise ValueError("page must be positive")
        return self._get(
            self._history_url.format(
                lock_id=quote(source_lock_id, safe=""), page=page
            )
        )

    def _get(self, url: str) -> object:
        request = Request(
            url,
            headers={"Authorization": self._authorization, "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read(self._maximum + 1)
        except (OSError, TimeoutError, URLError) as error:
            raise QrioTransportError("Qrio read request failed") from error
        if len(payload) > self._maximum:
            raise QrioTransportError("Qrio response exceeds configured maximum")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise QrioTransportError("Qrio response is invalid JSON") from error


def _require_safe_https_url(name: str, value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            f"{name} must be an HTTPS URL without credentials or fragment"
        )
