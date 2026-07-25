from __future__ import annotations

import json
from pathlib import Path

import pytest

from hedp.adapters.smartledz import (
    DecodedResponse,
    MessageError,
    Quality,
    ReadRequest,
    ResourceKind,
    correlate_read_responses,
)


FIXTURES = Path(__file__).parent / "fixtures" / "smartledz"


def _fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_correlates_all_read_only_resources_by_frame_request_id() -> None:
    resource_by_request_id = {
        31: ResourceKind.GROUP,
        4: ResourceKind.SCENE,
        18: ResourceKind.SCHEDULE,
        9: ResourceKind.DEVICE,
        22: ResourceKind.SENSOR,
    }
    messages = _fixture("read_response_envelopes_v1.json")
    requests = tuple(
        ReadRequest(resource=resource_by_request_id[message["request_id"]], request_id=message["request_id"])
        for message in reversed(messages)
    )
    responses = tuple(
        DecodedResponse(
            request_id=message["request_id"], response=message["response"]
        )
        for message in messages
    )

    correlated = correlate_read_responses(requests, responses)

    assert [result.resource for result in correlated] == list(reversed(list(ResourceKind)))
    assert [result.request_id for result in correlated] == [22, 9, 18, 4, 31]
    assert all(result.envelope.quality == Quality.GOOD for result in correlated)
    assert all(result.envelope.error_code == 0 for result in correlated)
    assert all(result.envelope.unknown_fields == ("Data", "futureEnvelope") for result in correlated)


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ((), "missing response"),
        ((DecodedResponse(2, {"ErrorCode": 0}),), "not declared"),
        (
            (
                DecodedResponse(1, {"ErrorCode": 0}),
                DecodedResponse(1, {"ErrorCode": 0}),
            ),
            "duplicate response",
        ),
        ((DecodedResponse(1, {"ErrorCode": 0}, notification=True),), "notification"),
    ],
)
def test_rejects_incomplete_or_ambiguous_correlations(
    responses: tuple[DecodedResponse, ...], message: str
) -> None:
    with pytest.raises(MessageError, match=message):
        correlate_read_responses([ReadRequest(ResourceKind.GROUP, 1)], responses)


def test_rejects_duplicate_request_ids_and_resources() -> None:
    response = [DecodedResponse(1, {"ErrorCode": 0})]

    with pytest.raises(MessageError, match="duplicate declared"):
        correlate_read_responses(
            [ReadRequest(ResourceKind.GROUP, 1), ReadRequest(ResourceKind.SCENE, 1)],
            response,
        )
    with pytest.raises(MessageError, match="resource was declared"):
        correlate_read_responses(
            [ReadRequest(ResourceKind.GROUP, 1), ReadRequest(ResourceKind.GROUP, 2)],
            response,
        )


@pytest.mark.parametrize("request_id", [False, -1, 64])
def test_request_ids_share_the_confirmed_frame_range(request_id: object) -> None:
    error = TypeError if isinstance(request_id, bool) else ValueError

    with pytest.raises(error):
        ReadRequest(ResourceKind.GROUP, request_id)  # type: ignore[arg-type]
    with pytest.raises(error):
        DecodedResponse(request_id, {"ErrorCode": 0})  # type: ignore[arg-type]


def test_decoded_responses_require_json_objects_and_do_not_render_values() -> None:
    with pytest.raises(TypeError, match="JSON object"):
        DecodedResponse(1, [])  # type: ignore[arg-type]

    response = DecodedResponse(1, {"ErrorCode": 0, "Data": "private value"})

    assert "private value" not in repr(response)


def test_message_fixture_is_anonymous() -> None:
    text = (FIXTURES / "read_response_envelopes_v1.json").read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "192.168." not in text
    forbidden = {
        "address",
        "auth",
        "ip",
        "mac",
        "name",
        "password",
        "token",
        "udn",
    }
    assert not forbidden.intersection(_all_keys(payload))


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_all_keys(nested))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested in value:
            keys.update(_all_keys(nested))
        return keys
    return set()
