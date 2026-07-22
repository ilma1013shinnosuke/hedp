from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from hedp.storage import Record


def test_json_round_trip() -> None:
    record = Record(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, 1, 2, 3, tzinfo=timezone.utc),
        metric="productPower",
        value=42.5,
        unit="kW",
    )

    assert Record.from_json(record.to_json()) == record


def test_record_is_immutable() -> None:
    record = Record(
        source="fusionsolar",
        timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
        metric="productPower",
        value=42,
        unit="kW",
    )

    with pytest.raises(FrozenInstanceError):
        record.value = 43
