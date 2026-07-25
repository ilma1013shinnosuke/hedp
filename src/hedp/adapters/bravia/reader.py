from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import NormalizedState
from .normalizer import normalize_content, normalize_power, normalize_volume


@dataclass(frozen=True)
class ReadBatch:
    """別のtransportが取得したread-only応答だけを受け取るオフライン境界。"""

    power_response: Mapping[str, Any]
    volume_response: Mapping[str, Any]
    content_response: Mapping[str, Any]
    observed_at: str
    received_at: str
    unknown: dict[str, Any] = field(default_factory=dict)


def normalize_read_batch(batch: ReadBatch) -> NormalizedState:
    """通信、認証、再試行、操作を一切行わず、取得済み応答を正規化する。"""

    return NormalizedState(
        power=normalize_power(batch.power_response),
        audio=normalize_volume(batch.volume_response),
        content=normalize_content(batch.content_response),
        observed_at=batch.observed_at,
        received_at=batch.received_at,
        unknown=dict(batch.unknown),
    )
