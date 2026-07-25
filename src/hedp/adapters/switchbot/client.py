from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any, Callable

import requests


class SwitchBotClient:
    BASE_URL = "https://api.switch-bot.com/v1.1"

    def __init__(
        self,
        token: str,
        secret: str,
        *,
        clock_ms: Callable[[], int] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        timeout_seconds: float = 30,
        max_attempts: int = 1,
        retry_backoff_seconds: float = 0,
        sleeper: Callable[[float], None] | None = None,
        request_get: Callable[..., requests.Response] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self._token = token
        self._secret = secret
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._nonce_factory = nonce_factory or (lambda: uuid.uuid4().hex)
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleeper = sleeper or time.sleep
        self._request_get = request_get or requests.get

    def authentication_headers(self) -> dict[str, str]:
        timestamp = str(self._clock_ms())
        nonce = self._nonce_factory()
        value = f"{self._token}{timestamp}{nonce}".encode()
        signature = base64.b64encode(
            hmac.new(self._secret.encode(), value, hashlib.sha256).digest()
        ).decode()
        return {
            "Authorization": self._token,
            "sign": signature,
            "nonce": nonce,
            "t": timestamp,
            "Content-Type": "application/json; charset=utf8",
        }

    def get_json(self, path: str) -> dict[str, Any]:
        response: requests.Response | None = None
        for attempt in range(self._max_attempts):
            try:
                response = self._request_get(
                    f"{self.BASE_URL}{path}",
                    headers=self.authentication_headers(),
                    timeout=self._timeout_seconds,
                )
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 >= self._max_attempts:
                    raise
                if self._retry_backoff_seconds:
                    self._sleeper(self._retry_backoff_seconds)
        if response is None:  # Defensive: the bounded loop always sets or raises.
            raise RuntimeError("SwitchBot request did not produce a response")
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("SwitchBot response is not a JSON object")
        return result

    def devices(self) -> dict[str, Any]:
        return self.get_json("/devices")

    def status(self, device_id: str) -> dict[str, Any]:
        return self.get_json(f"/devices/{device_id}/status")
