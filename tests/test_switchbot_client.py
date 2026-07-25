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


def test_read_only_retry_is_bounded_and_generates_fresh_authentication():
    responses = [
        requests.Timeout("first"),
        Mock(json=lambda: {"statusCode": 100, "body": {}}),
    ]
    request_get = Mock(side_effect=responses)
    request_get.return_value = responses[-1]
    responses[-1].raise_for_status = Mock()
    nonces = iter(("nonce-1", "nonce-2"))
    client = SwitchBotClient(
        "token",
        "secret",
        nonce_factory=lambda: next(nonces),
        request_get=request_get,
        max_attempts=2,
    )

    assert client.devices()["statusCode"] == 100
    assert request_get.call_count == 2
    assert request_get.call_args_list[0].kwargs["headers"]["nonce"] == "nonce-1"
    assert request_get.call_args_list[1].kwargs["headers"]["nonce"] == "nonce-2"


def test_retry_configuration_rejects_unbounded_or_invalid_values():
    with pytest.raises(ValueError, match="positive"):
        SwitchBotClient("token", "secret", timeout_seconds=0)
    with pytest.raises(ValueError, match="at least one"):
        SwitchBotClient("token", "secret", max_attempts=0)
