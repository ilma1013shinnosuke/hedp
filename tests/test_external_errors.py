from unittest.mock import Mock

import requests

from hedp.adapters.external_errors import (
    AUTHENTICATION_REQUIRED,
    ExternalServiceError,
    normalize_external_error,
)


def test_normalized_error_has_only_safe_machine_fields() -> None:
    report = normalize_external_error(
        RuntimeError("private upstream body: credential=value")
    ).as_dict()

    assert report == {
        "error_type": "unexpected_error",
        "category": "internal",
        "code": "unexpected_error",
        "retryable": False,
    }
    assert "credential" not in repr(report)


def test_http_error_status_is_classified_without_response_body() -> None:
    response = Mock(status_code=503, text="private upstream body")
    error = requests.HTTPError("private upstream body", response=response)

    report = normalize_external_error(error).as_dict()

    assert report == {
        "error_type": "service_unavailable",
        "category": "service",
        "code": "service_unavailable",
        "retryable": True,
    }
    assert "private" not in repr(report)


def test_external_service_error_message_excludes_upstream_detail() -> None:
    error = ExternalServiceError(AUTHENTICATION_REQUIRED)

    assert str(error) == "External service error: authentication_action_required"
    assert "CAPTCHA" not in str(error)
