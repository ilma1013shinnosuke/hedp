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
    ) -> None:
        self._token = token
        self._secret = secret
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._nonce_factory = nonce_factory or (lambda: uuid.uuid4().hex)

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
        response = requests.get(
            f"{self.BASE_URL}{path}",
            headers=self.authentication_headers(),
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("SwitchBot response is not a JSON object")
        return result

    def devices(self) -> dict[str, Any]:
        return self.get_json("/devices")

    def status(self, device_id: str) -> dict[str, Any]:
        return self.get_json(f"/devices/{device_id}/status")
