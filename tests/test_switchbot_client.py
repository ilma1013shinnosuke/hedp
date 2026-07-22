import base64
import hashlib
import hmac
from unittest.mock import Mock, patch

import pytest
import requests

from hedp.adapters.switchbot.client import SwitchBotClient


def test_signature_uses_fixed_time_and_nonce():
    client = SwitchBotClient(
        "token", "secret", clock_ms=lambda: 1234,
        nonce_factory=lambda: "nonce",
    )
    headers = client.authentication_headers()
    expected = base64.b64encode(
        hmac.new(b"secret", b"token1234nonce", hashlib.sha256).digest()
    ).decode()
    assert headers == {
        "Authorization": "token", "sign": expected, "nonce": "nonce",
        "t": "1234", "Content-Type": "application/json; charset=utf8",
    }


def test_devices_and_status_use_v11_get_without_logging_credentials():
    response = Mock()
    response.json.return_value = {"statusCode": 100, "body": {"future": 1}}
    with patch("hedp.adapters.switchbot.client.requests.get", return_value=response) as get:
        client = SwitchBotClient("token", "secret")
        assert client.devices()["body"]["future"] == 1
        client.status("device")
    assert get.call_args_list[0].args[0].endswith("/v1.1/devices")
    assert get.call_args_list[1].args[0].endswith("/devices/device/status")
    assert get.call_args_list[0].kwargs["timeout"] == 30


def test_timeout_propagates_without_embedding_secret():
    with patch(
        "hedp.adapters.switchbot.client.requests.get",
        side_effect=requests.Timeout("timeout"),
    ):
        with pytest.raises(requests.Timeout) as raised:
            SwitchBotClient("token", "secret").devices()
    assert "secret" not in str(raised.value)
