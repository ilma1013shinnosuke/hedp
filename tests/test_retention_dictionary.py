from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_retention_dictionary import (
    validate_retention_dictionary,
)


ROOT = Path(__file__).parents[1]
EXAMPLE = (
    ROOT / "docs/templates/retention-data-dictionary.example.json"
)
SCHEMA = (
    ROOT / "docs/schemas/retention-data-dictionary-v1.schema.json"
)


def example() -> dict[str, object]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_draft_template_is_structurally_valid_and_anonymous() -> None:
    value = example()

    assert validate_retention_dictionary(value) == ()
    encoded = json.dumps(value)
    assert "room" not in encoded.casefold()
    assert "device_id" not in encoded.casefold()
    assert "192.168." not in encoded


def test_approved_dictionary_cannot_keep_unbounded_unknowns() -> None:
    value = example()
    value["status"] = "approved"

    issues = validate_retention_dictionary(value)

    assert len(issues) == 1
    assert issues[0].startswith(
        "approved dictionary has unresolved fields:"
    )


def test_approved_bounded_dictionary_is_valid() -> None:
    value = example()
    value.update(
        {
            "status": "approved",
            "max_payload_bytes": 4096,
            "max_events_per_day": 288,
            "estimated_daily_bytes": 1179648,
            "active_detail_days": 90,
            "long_term_granularity": "1 hour",
            "long_term_retention_days": 3650,
            "archive_unit": "source_schema_month",
            "compression": "gzip",
            "restore_procedure": "docs/data-retention-policy.md",
        }
    )

    assert validate_retention_dictionary(value) == ()


def test_schema_and_validator_require_the_same_top_level_fields() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["required"]) == set(example())


def test_interval_data_kinds_are_valid() -> None:
    for data_kind in ("state_interval", "observation_coverage"):
        value = example()
        value["data_kind"] = data_kind

        assert validate_retention_dictionary(value) == ()
