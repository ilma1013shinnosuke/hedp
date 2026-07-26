from __future__ import annotations

import json

import pytest

from hedp.adapters.miele import (
    MieleReadOnlyHttpTransport,
    MieleTransportError,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object | None = None,
        lines: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = json.dumps(payload).encode() if payload is not None else b""
        self._lines = lines or []
        self.closed = False

    def iter_lines(self):
        yield from self._lines

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return next(self._responses)


def _transport(session: FakeSession) -> MieleReadOnlyHttpTransport:
    return MieleReadOnlyHttpTransport(
        devices_url="https://fixture.invalid/v1/devices",
        events_url="https://fixture.invalid/v1/events",
        access_token="fixture-token",
        session=session,
    )


def test_rest_is_one_get_without_redirect_or_secret_output() -> None:
    response = FakeResponse(payload={"fixture-device": {"state": {}}})
    session = FakeSession([response])

    result = _transport(session).devices()

    assert result == {"fixture-device": {"state": {}}}
    _, options = session.calls[0]
    assert options["allow_redirects"] is False
    assert options["stream"] is False
    assert options["timeout"] == 15
    assert response.closed


def test_sse_is_one_finite_get_and_closes_connection() -> None:
    response = FakeResponse(
        lines=[
            b"event: PING",
            b"data: {}",
            b"",
            b"event: ACTION",
            b'data: {"state":{"status":{"value_raw":5}}}',
            b"",
            b"event: ACTION",
            b'data: {"state":{"status":{"value_raw":6}}}',
            b"",
        ]
    )
    session = FakeSession([response])

    events = list(
        _transport(session).events(
            "fixture-device",
            maximum_events=2,
            timeout_seconds=7,
        )
    )

    assert [event.name for event in events] == ["PING", "ACTION"]
    _, options = session.calls[0]
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert options["timeout"] == 7
    assert response.closed


@pytest.mark.parametrize(
    "devices_url,events_url",
    [
        ("http://fixture.invalid/devices", "https://fixture.invalid/events"),
        ("https://user@fixture.invalid/devices", "https://fixture.invalid/events"),
        ("https://fixture.invalid/devices", "file:///tmp/events"),
    ],
)
def test_transport_rejects_unsafe_urls(
    devices_url: str,
    events_url: str,
) -> None:
    with pytest.raises(ValueError, match="HTTPS URL"):
        MieleReadOnlyHttpTransport(
            devices_url=devices_url,
            events_url=events_url,
            access_token="fixture-token",
        )


def test_errors_do_not_include_url_token_or_response() -> None:
    response = FakeResponse(status_code=401, payload={"private": "response-secret"})
    transport = _transport(FakeSession([response]))

    with pytest.raises(MieleTransportError) as caught:
        transport.devices()

    rendered = str(caught.value)
    assert "fixture.invalid" not in rendered
    assert "fixture-token" not in rendered
    assert "response-secret" not in rendered
