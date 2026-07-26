from __future__ import annotations

import pytest

from hedp.adapters.qrio import QrioHttpsReadTransport, QrioTransportError


class Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.payload[:limit]


def test_https_transport_uses_get_bounded_timeout_and_encoded_identifier() -> None:
    calls = []

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        return Response(b'{"main_lock":2}')

    transport = QrioHttpsReadTransport(
        status_url_template="https://fixture.invalid/locks/{lock_id}",
        health_url="https://fixture.invalid/health",
        history_url_template="https://fixture.invalid/locks/{lock_id}/history?page={page}",
        authorization="fixture-authorization",
        timeout_seconds=7,
        opener=open_request,
    )

    assert transport.status("lock/id") == {"main_lock": 2}
    request, timeout = calls[0]
    assert request.method == "GET"
    assert request.full_url.endswith("/locks/lock%2Fid")
    assert timeout == 7


def test_https_transport_rejects_http_and_unbounded_timeout() -> None:
    common = {
        "status_url_template": "https://fixture.invalid/{lock_id}",
        "health_url": "https://fixture.invalid/health",
        "history_url_template": "https://fixture.invalid/{lock_id}?page={page}",
        "authorization": "fixture",
    }
    with pytest.raises(ValueError, match="HTTPS"):
        QrioHttpsReadTransport(**{**common, "health_url": "http://fixture.invalid"})
    with pytest.raises(ValueError, match="at most 30"):
        QrioHttpsReadTransport(**common, timeout_seconds=31)


def test_https_transport_rejects_url_credentials_and_fragments() -> None:
    common = {
        "status_url_template": "https://fixture.invalid/{lock_id}",
        "health_url": "https://fixture.invalid/health",
        "history_url_template": "https://fixture.invalid/{lock_id}?page={page}",
        "authorization": "fixture",
    }
    with pytest.raises(ValueError, match="without credentials"):
        QrioHttpsReadTransport(
            **{**common, "health_url": "https://user:secret@fixture.invalid/health"}
        )
    with pytest.raises(ValueError, match="without credentials"):
        QrioHttpsReadTransport(
            **{**common, "health_url": "https://fixture.invalid/health#private"}
        )


def test_https_transport_wraps_response_and_network_errors_without_details() -> None:
    common = {
        "status_url_template": "https://fixture.invalid/{lock_id}",
        "health_url": "https://fixture.invalid/health",
        "history_url_template": "https://fixture.invalid/{lock_id}?page={page}",
        "authorization": "fixture",
    }
    invalid = QrioHttpsReadTransport(
        **common,
        opener=lambda *_args, **_kwargs: Response(b"not-json-private-data"),
    )
    with pytest.raises(QrioTransportError, match="invalid JSON") as invalid_error:
        invalid.health()
    assert "private-data" not in str(invalid_error.value)

    def unavailable(*_args, **_kwargs):
        raise OSError("https://household.invalid/private")

    failed = QrioHttpsReadTransport(**common, opener=unavailable)
    with pytest.raises(QrioTransportError, match="read request failed") as network_error:
        failed.health()
    assert "household.invalid" not in str(network_error.value)
