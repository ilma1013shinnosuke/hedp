from __future__ import annotations

import json
from pathlib import Path

from hedp.adapters.bravia import (
    ErrorCategory,
    PowerState,
    Quality,
    ReadBatch,
    normalize_content,
    normalize_power,
    normalize_read_batch,
    normalize_volume,
)


FIXTURES = Path(__file__).parent / "fixtures" / "bravia"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _batch(name: str) -> ReadBatch:
    payload = _fixture(name)
    return ReadBatch(
        power_response=payload["responses"]["power"],
        volume_response=payload["responses"]["volume"],
        content_response=payload["responses"]["content"],
        observed_at=payload["observed_at"],
        received_at=payload["received_at"],
    )


def test_active_snapshot_normalizes_zero_safe_values_and_unknown_fields() -> None:
    state = normalize_read_batch(_batch("active_anonymous.json"))

    assert state.power.value == PowerState.ACTIVE
    assert state.power.quality == Quality.GOOD
    assert state.power.unknown == {
        "field_count": 1,
        "result_field_count": 1,
    }
    assert state.audio.quality == Quality.GOOD
    assert state.audio.outputs[0].volume == 0
    assert state.audio.outputs[0].muted is False
    assert state.audio.outputs[0].minimum == 0
    assert state.audio.outputs[0].unknown == {"field_count": 1}
    assert state.content.source == "extInput"
    assert state.content.unknown == {}
    assert state.content.omitted_private_fields == ("uri",)


def test_standby_snapshot_does_not_invent_unavailable_active_state() -> None:
    state = normalize_read_batch(_batch("standby_missing_anonymous.json"))

    assert state.power.value == PowerState.STANDBY
    assert state.audio.quality == Quality.MISSING
    assert state.audio.outputs == ()
    assert state.content.quality == Quality.MISSING
    assert state.content.error is not None
    assert state.content.error.category == ErrorCategory.INVALID_STATE
    assert state.content.error.retryable is False


def test_unknown_and_invalid_values_are_not_coerced() -> None:
    state = normalize_read_batch(_batch("unknown_schema_anonymous.json"))

    assert state.power.value == PowerState.UNKNOWN
    assert state.power.raw_value is None
    assert state.power.quality == Quality.UNKNOWN
    assert state.audio.outputs[0].volume is None
    assert state.audio.outputs[0].muted is None
    assert state.audio.outputs[0].quality == Quality.INVALID
    assert state.content.quality == Quality.MISSING
    assert state.content.unknown == {}


def test_viewing_titles_are_omitted_from_normalized_content() -> None:
    content = normalize_content(
        {
            "id": 10,
            "result": [
                {
                    "source": "tv",
                    "title": "sensitive-program-name",
                    "programTitle": "sensitive-program-name",
                    "durationSec": 120,
                    "futureField": "not-retained",
                }
            ],
        }
    )

    assert content.source == "tv"
    assert content.omitted_private_fields == ("durationSec", "programTitle", "title")
    assert content.unknown == {}
    assert not hasattr(content, "title")
    assert "sensitive-program-name" not in repr(content)


def test_api_error_categories_do_not_retain_error_detail() -> None:
    authentication = normalize_power({"error": [401, "sensitive detail"]})
    temporary = normalize_volume({"error": [503, "sensitive detail"]})
    malformed = normalize_content({"error": "not-an-array"})

    assert authentication.error is not None
    assert authentication.error.category == ErrorCategory.AUTHENTICATION
    assert authentication.error.retryable is False
    assert "sensitive detail" not in repr(authentication)
    assert temporary.error is not None
    assert temporary.error.category == ErrorCategory.TEMPORARY
    assert temporary.error.retryable is True
    assert malformed.error is not None
    assert malformed.error.category == ErrorCategory.MALFORMED_RESPONSE


def test_malformed_envelopes_are_invalid_not_zero_or_empty_success() -> None:
    power = normalize_power({"result": {"status": "active"}})
    volume = normalize_volume({"result": [{"target": "speaker"}]})
    content = normalize_content({"result": [False]})

    assert power.quality == Quality.INVALID
    assert power.value == PowerState.UNKNOWN
    assert volume.quality == Quality.INVALID
    assert volume.outputs == ()
    assert content.quality == Quality.INVALID


def test_content_safe_output_never_retains_viewing_text_or_identifiers() -> None:
    private_text = "do-not-retain-viewing-data"
    private_identifier = "private-content-id"
    content = normalize_content(
        {
            "title": private_text,
            "result": [
                {
                    "source": "tv",
                    "uri": f"content://{private_identifier}",
                    "dispNum": "123",
                    "title": private_text,
                    "programTitle": private_text,
                    "description": private_text,
                    "contentId": private_identifier,
                    "future": {
                        "title": private_text,
                        "id": private_identifier,
                    },
                }
            ],
        }
    )

    assert content.source == "tv"
    assert content.unknown == {}
    assert content.omitted_private_fields == (
        "contentId",
        "description",
        "dispNum",
        "programTitle",
        "title",
        "uri",
    )
    assert private_text not in repr(content)
    assert private_identifier not in repr(content)


def test_unknown_power_audio_and_batch_values_keep_counts_only() -> None:
    batch = ReadBatch(
        power_response={
            "Authorization": "token-secret",
            "result": [{"status": "active", "serial": "serial-secret"}],
        },
        volume_response={
            "result": [
                [
                    {
                        "target": "speaker",
                        "volume": 10,
                        "mute": False,
                        "mac": "mac-secret",
                    }
                ]
            ]
        },
        content_response={"result": [{"source": "tv"}]},
        observed_at="2026-07-25T00:00:00Z",
        received_at="2026-07-25T00:00:01Z",
        unknown={"cookie": "cookie-secret"},
    )
    state = normalize_read_batch(batch)

    assert state.power.unknown == {
        "field_count": 1,
        "result_field_count": 1,
    }
    assert state.audio.outputs[0].unknown == {"field_count": 1}
    assert state.unknown == {"field_count": 1}
    rendered = repr(state)
    for private in (
        "token-secret",
        "serial-secret",
        "mac-secret",
        "cookie-secret",
    ):
        assert private not in repr(batch)
        assert private not in rendered


def test_malformed_batch_member_does_not_discard_successful_siblings() -> None:
    state = normalize_read_batch(
        ReadBatch(
            power_response={"result": [{"status": "active"}]},
            volume_response=None,  # type: ignore[arg-type]
            content_response={"result": [{"source": "tv"}]},
            observed_at="2026-07-25T00:00:00Z",
            received_at="2026-07-25T00:00:01Z",
        )
    )

    assert state.power.value == PowerState.ACTIVE
    assert state.power.quality == Quality.GOOD
    assert state.audio.quality == Quality.INVALID
    assert state.audio.reason == "payload_not_object"
    assert state.content.source == "tv"
    assert state.content.quality == Quality.GOOD


def test_volume_non_object_row_is_invalid_not_silent_success() -> None:
    audio = normalize_volume(
        {
            "result": [
                [
                    {"target": "speaker", "volume": 0, "mute": False},
                    "malformed",
                ]
            ]
        }
    )

    assert audio.outputs[0].volume == 0
    assert audio.quality == Quality.INVALID
    assert audio.reason == "result_row_not_object"
    assert audio.error is not None
    assert audio.error.category == ErrorCategory.MALFORMED_RESPONSE


def test_bravia_fixtures_do_not_contain_secrets_or_viewing_titles() -> None:
    forbidden_keys = {
        "title",
        "programTitle",
        "psk",
        "password",
        "token",
        "cookie",
        "serial",
        "mac",
        "ip",
    }
    for path in FIXTURES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
        assert not forbidden_keys.intersection(_all_keys(payload))
        assert "192.168." not in text


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
