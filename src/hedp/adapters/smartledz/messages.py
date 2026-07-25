"""Offline validation and correlation for decoded Smart LEDZ read responses.

The JSON command names and request-object schema have not been retained as
anonymous, repository-confirmed knowledge.  This module therefore does not
construct a Smart LEDZ JSON request.  A transport boundary supplies the frame
request ID and an already-decoded JSON object; this module safely associates
that object with a declared read-only resource.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .framing import REQUEST_ID_MASK
from .models import ResourceKind, ResourceResponse
from .normalizer import normalize_resource_response


class MessageError(ValueError):
    """A decoded read response cannot be safely correlated."""


def _validate_request_id(request_id: int) -> None:
    if isinstance(request_id, bool) or not isinstance(request_id, int):
        raise TypeError("request_id must be an integer")
    if not 0 <= request_id <= REQUEST_ID_MASK:
        raise ValueError("request_id must be between 0 and 63")


@dataclass(frozen=True)
class ReadRequest:
    """One declared read-only resource request, without a JSON command body."""

    resource: ResourceKind
    request_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceKind):
            raise TypeError("resource must be a ResourceKind")
        _validate_request_id(self.request_id)


@dataclass(frozen=True)
class DecodedResponse:
    """A JSON object decoded by a separate transport boundary.

    ``request_id`` comes from the matching Smart LEDZ frame, not from an
    assumed JSON field.  The response is deliberately omitted from ``repr``
    because its unconfirmed fields may contain private information.
    """

    request_id: int
    response: Mapping[object, object] = field(repr=False)
    notification: bool = False

    def __post_init__(self) -> None:
        _validate_request_id(self.request_id)
        if not isinstance(self.response, Mapping):
            raise TypeError("response must be a decoded JSON object")
        if not isinstance(self.notification, bool):
            raise TypeError("notification must be a boolean")


@dataclass(frozen=True)
class CorrelatedReadResponse:
    """A validated response associated with its declared read resource."""

    resource: ResourceKind
    request_id: int
    envelope: ResourceResponse


def correlate_read_responses(
    requests: Iterable[ReadRequest], responses: Iterable[DecodedResponse]
) -> tuple[CorrelatedReadResponse, ...]:
    """Validate complete, one-to-one correlation of decoded read responses.

    This intentionally neither sends requests nor assumes a JSON command or
    response-ID field.  Notifications are excluded because they are not a
    response to a declared read request.  Each correlated JSON object is then
    passed to the existing conservative ``ErrorCode`` envelope validator.
    """

    declared = tuple(requests)
    received = tuple(responses)
    if not declared:
        raise MessageError("at least one read request is required")

    request_ids: dict[int, ReadRequest] = {}
    resources: set[ResourceKind] = set()
    for request in declared:
        if not isinstance(request, ReadRequest):
            raise TypeError("requests must contain ReadRequest instances")
        if request.request_id in request_ids:
            raise MessageError("duplicate declared request ID")
        if request.resource in resources:
            raise MessageError("resource was declared more than once")
        request_ids[request.request_id] = request
        resources.add(request.resource)

    matched: dict[int, DecodedResponse] = {}
    for response in received:
        if not isinstance(response, DecodedResponse):
            raise TypeError("responses must contain DecodedResponse instances")
        if response.notification:
            raise MessageError("notification cannot be correlated to a read request")
        if response.request_id not in request_ids:
            raise MessageError("response request ID was not declared")
        if response.request_id in matched:
            raise MessageError("duplicate response request ID")
        matched[response.request_id] = response

    if missing := set(request_ids).difference(matched):
        raise MessageError(f"missing response for {len(missing)} read request(s)")

    return tuple(
        CorrelatedReadResponse(
            resource=request.resource,
            request_id=request.request_id,
            envelope=normalize_resource_response(
                request.resource, matched[request.request_id].response
            ),
        )
        for request in declared
    )
