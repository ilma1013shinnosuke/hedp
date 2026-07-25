from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ErrorCategory(str, Enum):
    AUTHENTICATION = "authentication"
    INVALID_STATE = "invalid_state"
    OPERATION_REJECTED = "operation_rejected"
    TEMPORARY = "temporary"
    TRANSPORT = "transport"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ApiError:
    """ログへ応答本文を持ち込まない、最小のAPIエラー表現。"""

    category: ErrorCategory
    code: int | None = None
    retryable: bool = False


_INVALID_STATE_CODES = frozenset({7, 40005})
_OPERATION_REJECTED_CODES = frozenset(
    {40800, 40801, 41001, 41011, 41012, 41400, 41401, 41402}
)
_TEMPORARY_CODES = frozenset({500, 502, 503, 504})


def classify_error(payload: Mapping[str, Any]) -> ApiError | None:
    """Sony形式のerror配列を分類し、説明文は秘密混入を避けて捨てる。"""

    if "error" not in payload:
        return None
    raw_error = payload["error"]
    if not isinstance(raw_error, list) or not raw_error:
        return ApiError(ErrorCategory.MALFORMED_RESPONSE)

    raw_code = raw_error[0]
    code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
    if code in {401, 403}:
        return ApiError(ErrorCategory.AUTHENTICATION, code)
    if code in _INVALID_STATE_CODES:
        return ApiError(ErrorCategory.INVALID_STATE, code)
    if code in _OPERATION_REJECTED_CODES:
        return ApiError(ErrorCategory.OPERATION_REJECTED, code)
    if code in _TEMPORARY_CODES:
        return ApiError(ErrorCategory.TEMPORARY, code, retryable=True)
    return ApiError(ErrorCategory.UNKNOWN, code)
