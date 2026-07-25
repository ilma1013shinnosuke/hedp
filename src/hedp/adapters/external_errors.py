"""Safe, machine-readable error summaries for external integrations.

External services can include credentials, URLs, device identifiers, or other
private details in exception text.  Those details must not cross an adapter
boundary into a CLI result or an application log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import requests


@dataclass(frozen=True)
class ExternalErrorReport:
    """The only error shape adapters may return or log for remote failures."""

    error_type: str
    category: str
    code: str
    retryable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "error_type": self.error_type,
            "category": self.category,
            "code": self.code,
            "retryable": self.retryable,
        }


class ExternalServiceError(RuntimeError):
    """An external failure without an upstream message, URL, or payload."""

    def __init__(self, report: ExternalErrorReport) -> None:
        self.report = report
        super().__init__(f"External service error: {report.code}")


AUTHENTICATION_REQUIRED: Final = ExternalErrorReport(
    error_type="authentication_required",
    category="authentication",
    code="authentication_action_required",
    retryable=False,
)
AUTHENTICATION_FAILED: Final = ExternalErrorReport(
    error_type="authentication_failed",
    category="authentication",
    code="authentication_failed",
    retryable=False,
)
INVALID_RESPONSE: Final = ExternalErrorReport(
    error_type="invalid_response",
    category="response",
    code="invalid_response",
    retryable=True,
)


def normalize_external_error(error: BaseException) -> ExternalErrorReport:
    """Classify an exception without retaining its potentially private text."""
    if isinstance(error, ExternalServiceError):
        return error.report
    if isinstance(error, (requests.Timeout, TimeoutError)):
        return ExternalErrorReport("timeout", "network", "request_timeout", True)
    if isinstance(error, requests.ConnectionError):
        return ExternalErrorReport(
            "connection_failed", "network", "connection_failed", True
        )
    if isinstance(error, requests.HTTPError):
        status_code = getattr(error.response, "status_code", None)
        if status_code == 429 or (
            isinstance(status_code, int) and status_code >= 500
        ):
            return ExternalErrorReport(
                "service_unavailable", "service", "service_unavailable", True
            )
        if status_code in {401, 403}:
            return AUTHENTICATION_FAILED
        return ExternalErrorReport(
            "request_rejected", "service", "request_rejected", False
        )
    if isinstance(error, requests.RequestException):
        return ExternalErrorReport("request_failed", "network", "request_failed", True)
    if isinstance(error, ValueError):
        return INVALID_RESPONSE
    return ExternalErrorReport(
        "unexpected_error", "internal", "unexpected_error", False
    )
