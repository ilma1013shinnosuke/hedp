from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hedp.adapters.eufy_weather import (
    EnergyAwareSnapshotPolicy,
    EnergyEvidence,
    EnergyGatedCollectionResult,
    EufyWeatherCapabilities,
    EufyWeatherCollector,
    EufyWeatherConfiguration,
    NormalizedRoi,
    OpenCvSnapshotReader,
    RgbFrame,
    SnapshotAction,
    SnapshotBackendUnavailable,
    SnapshotTimeout,
    SunlightCalibration,
    SunlightState,
    analyze_sunlight,
    collect_if_energy_allows,
    decide_snapshot_acquisition,
    eufy_weather_configuration_from_mapping,
    qualification_report,
)
from hedp.observations import ObservedValue, Quality


FIXTURES = Path(__file__).parent / "fixtures" / "eufy_weather"
NOW = datetime(2026, 7, 27, 1, 0, 1, tzinfo=timezone.utc)


def _fixture_frame() -> tuple[RgbFrame, NormalizedRoi, NormalizedRoi]:
    payload = json.loads(
        (FIXTURES / "direct_sun_anonymous.json").read_text(encoding="utf-8")
    )
    return (
        RgbFrame(
            pixels=tuple(
                tuple(tuple(pixel) for pixel in row)
                for row in payload["pixels"]
            ),
            captured_at=payload["captured_at"],
        ),
        NormalizedRoi(**payload["sky_roi"]),
        NormalizedRoi(**payload["shadow_roi"]),
    )


def _calibration() -> SunlightCalibration:
    return SunlightCalibration(
        direct_sun_min_illumination=0.7,
        direct_sun_min_shadow_contrast=0.4,
        low_light_max_illumination=0.1,
    )


def test_direct_sun_fixture_produces_relative_evidence_and_estimated_state() -> None:
    frame, sky_roi, shadow_roi = _fixture_frame()

    observation = analyze_sunlight(
        frame,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        calibration=_calibration(),
        clock=lambda: NOW,
    )

    assert observation.state.value == SunlightState.DIRECT_SUN
    assert observation.state.quality == Quality.ESTIMATED
    assert observation.illumination_index.value == pytest.approx(230 / 255)
    assert observation.shadow_contrast.value == pytest.approx(180 / 255)
    assert observation.quality == Quality.GOOD
    assert observation.attempt_count == 1
    assert "garden_weather_camera" not in repr(observation)
    assert "pixels" not in repr(frame)


def test_without_site_calibration_metrics_remain_good_but_state_is_unknown() -> None:
    frame, sky_roi, shadow_roi = _fixture_frame()

    observation = analyze_sunlight(
        frame,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        clock=lambda: NOW,
    )

    assert observation.quality == Quality.GOOD
    assert observation.illumination_index.quality == Quality.GOOD
    assert observation.state.value is None
    assert observation.state.quality == Quality.UNKNOWN
    assert observation.state.reason == "site_calibration_required"

    report = qualification_report(
        observation,
        target_alias="garden_weather_camera",
        source_mode="fixture",
    )
    assert report["status"] == "pass_with_calibration_pending"
    assert report["image_retained"] is False
    assert report["absolute_lux_claimed"] is False
    assert "pixels" not in json.dumps(report)
    assert "rtsp" not in json.dumps(report).lower()


def test_configuration_uses_environment_name_instead_of_rtsp_value() -> None:
    configuration = eufy_weather_configuration_from_mapping(
        {
            "target_alias": "garden_weather_camera",
            "stream_url_env": "HESTIA_EUFY_WEATHER_RTSP_URL",
            "sky_roi": {"x": 0, "y": 0, "width": 1, "height": 0.5},
            "shadow_roi": {"x": 0, "y": 0.5, "width": 1, "height": 0.5},
        }
    )

    assert isinstance(configuration, EufyWeatherConfiguration)
    assert configuration.stream_url_env == "HESTIA_EUFY_WEATHER_RTSP_URL"
    assert configuration.calibration is None
    assert configuration.energy_policy.normal_interval_minutes == 10


@pytest.mark.parametrize("forbidden_key", ["stream_url", "rtsp_url", "password"])
def test_configuration_rejects_inline_camera_secrets(forbidden_key: str) -> None:
    with pytest.raises(
        ValueError,
        match="camera credentials and URLs must not be stored",
    ):
        eufy_weather_configuration_from_mapping(
            {
                "target_alias": "garden_weather_camera",
                "stream_url_env": "HESTIA_EUFY_WEATHER_RTSP_URL",
                "sky_roi": {"x": 0, "y": 0, "width": 1, "height": 0.5},
                "shadow_roi": {
                    "x": 0,
                    "y": 0.5,
                    "width": 1,
                    "height": 0.5,
                },
                forbidden_key: "must-not-be-stored",
            }
        )


def test_configuration_rejects_nested_secret_fields_without_echoing_values() -> None:
    sensitive_value = "must-not-appear-in-error"
    with pytest.raises(ValueError) as error:
        eufy_weather_configuration_from_mapping(
            {
                "target_alias": "garden_weather_camera",
                "stream_url_env": "HESTIA_EUFY_WEATHER_RTSP_URL",
                "sky_roi": {"x": 0, "y": 0, "width": 1, "height": 0.5},
                "shadow_roi": {
                    "x": 0,
                    "y": 0.5,
                    "width": 1,
                    "height": 0.5,
                },
                "credentials": {"token": sensitive_value},
            }
        )

    assert sensitive_value not in str(error.value)


def test_configuration_rejects_unknown_fields_instead_of_ignoring_them() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        eufy_weather_configuration_from_mapping(
            {
                "target_alias": "garden_weather_camera",
                "stream_url_env": "HESTIA_EUFY_WEATHER_RTSP_URL",
                "sky_roi": {"x": 0, "y": 0, "width": 1, "height": 0.5},
                "shadow_roi": {
                    "x": 0,
                    "y": 0.5,
                    "width": 1,
                    "height": 0.5,
                },
                "misspelled_timeout": 12,
            }
        )


def test_uniform_bright_surface_is_diffuse_light_after_calibration() -> None:
    pixels = tuple(tuple((180, 180, 180) for _ in range(4)) for _ in range(4))
    frame = RgbFrame(pixels=pixels, captured_at="2026-07-27T01:00:00+00:00")
    full = NormalizedRoi(0, 0, 1, 1)

    observation = analyze_sunlight(
        frame,
        target_ref="garden_weather_camera",
        sky_roi=full,
        shadow_roi=full,
        calibration=_calibration(),
        clock=lambda: NOW,
    )

    assert observation.state.value == SunlightState.DIFFUSE_LIGHT
    assert observation.shadow_contrast.value == 0


def test_small_roi_is_invalid_instead_of_inventing_a_state() -> None:
    pixels = tuple(tuple((100, 100, 100) for _ in range(2)) for _ in range(2))
    frame = RgbFrame(pixels=pixels, captured_at="2026-07-27T01:00:00+00:00")
    full = NormalizedRoi(0, 0, 1, 1)

    observation = analyze_sunlight(
        frame,
        target_ref="garden_weather_camera",
        sky_roi=full,
        shadow_roi=full,
        calibration=_calibration(),
        clock=lambda: NOW,
    )

    assert observation.quality == Quality.INVALID
    assert observation.state.value is None
    assert observation.state.reason == "roi_too_small"


class _SequenceReader:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def read_snapshot(self, *, timeout_seconds: float) -> RgbFrame:
        assert timeout_seconds == 3
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, RgbFrame)
        return outcome


def test_collector_retries_once_only_for_retryable_snapshot_failure() -> None:
    frame, sky_roi, shadow_roi = _fixture_frame()
    reader = _SequenceReader([SnapshotTimeout(), frame])
    collector = EufyWeatherCollector(
        reader,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        calibration=_calibration(),
        timeout_seconds=3,
        maximum_attempts=2,
        clock=lambda: NOW,
    )

    observation = collector.collect()

    assert reader.calls == 2
    assert observation.quality == Quality.GOOD
    assert observation.attempt_count == 2


def test_collector_failure_uses_fixed_reason_and_never_leaks_exception_text() -> None:
    _, sky_roi, shadow_roi = _fixture_frame()
    sensitive_detail = "sensitive-upstream-detail-must-not-escape"
    reader = _SequenceReader([RuntimeError(sensitive_detail)])
    collector = EufyWeatherCollector(
        reader,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        timeout_seconds=3,
        clock=lambda: NOW,
    )

    observation = collector.collect()

    assert observation.quality == Quality.MISSING
    assert observation.state.reason == "snapshot_unexpected_error"
    assert sensitive_detail not in repr(observation)


def test_non_retryable_backend_failure_stops_without_second_attempt() -> None:
    _, sky_roi, shadow_roi = _fixture_frame()
    reader = _SequenceReader(
        [SnapshotBackendUnavailable(), AssertionError("must not retry")]
    )
    collector = EufyWeatherCollector(
        reader,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        timeout_seconds=3,
        maximum_attempts=2,
        clock=lambda: NOW,
    )

    observation = collector.collect()

    assert reader.calls == 1
    assert observation.state.reason == "snapshot_backend_unavailable"


def _energy_evidence(
    *,
    generation_kw: float,
    battery_soc_percent: float | None = None,
) -> EnergyEvidence:
    return EnergyEvidence(
        observed_at=NOW.isoformat(),
        rolling_generation_kw=ObservedValue(
            value=generation_kw,
            quality=Quality.GOOD,
        ),
        generation_window_minutes=10,
        rated_ac_kw=4.95,
        battery_soc_percent=(
            None
            if battery_soc_percent is None
            else ObservedValue(
                value=battery_soc_percent,
                quality=Quality.GOOD,
            )
        ),
    )


def _collector_with_reader(reader: _SequenceReader) -> EufyWeatherCollector:
    _, sky_roi, shadow_roi = _fixture_frame()
    return EufyWeatherCollector(
        reader,
        target_ref="garden_weather_camera",
        sky_roi=sky_roi,
        shadow_roi=shadow_roi,
        calibration=_calibration(),
        timeout_seconds=3,
        clock=lambda: NOW,
    )


def test_energy_gate_never_contacts_camera_when_generation_is_conclusive() -> None:
    reader = _SequenceReader([AssertionError("camera must not be contacted")])

    result = collect_if_energy_allows(
        _collector_with_reader(reader),
        _energy_evidence(generation_kw=4.0),
        now=NOW,
    )

    assert isinstance(result, EnergyGatedCollectionResult)
    assert result.decision.action == SnapshotAction.SKIP_HIGH_GENERATION
    assert result.observation is None
    assert reader.calls == 0


def test_energy_gate_never_contacts_camera_during_winter_scarcity() -> None:
    reader = _SequenceReader([AssertionError("camera must not be contacted")])
    winter_now = datetime(2026, 12, 1, 1, 0, 1, tzinfo=timezone.utc)
    evidence = EnergyEvidence(
        observed_at=winter_now.isoformat(),
        rolling_generation_kw=ObservedValue(
            value=0.2,
            quality=Quality.GOOD,
        ),
        generation_window_minutes=10,
        rated_ac_kw=4.95,
        battery_soc_percent=ObservedValue(
            value=20,
            quality=Quality.GOOD,
        ),
    )

    result = collect_if_energy_allows(
        _collector_with_reader(reader),
        evidence,
        now=winter_now,
    )

    assert result.decision.action == SnapshotAction.PAUSE_ENERGY_SCARCITY
    assert result.observation is None
    assert reader.calls == 0


def test_energy_gate_acquires_exactly_one_frame_when_evidence_is_useful() -> None:
    frame, _, _ = _fixture_frame()
    reader = _SequenceReader([frame])

    result = collect_if_energy_allows(
        _collector_with_reader(reader),
        _energy_evidence(generation_kw=1.0),
        now=NOW,
    )

    assert result.decision.action == SnapshotAction.ACQUIRE
    assert result.observation is not None
    assert result.observation.quality == Quality.GOOD
    assert reader.calls == 1


class _FakeFrame:
    shape = (2, 2, 3)

    def __init__(self) -> None:
        self.rows = [
            [(10, 20, 30), (40, 50, 60)],
            [(70, 80, 90), (100, 110, 120)],
        ]


class _FakeCapture:
    def __init__(self) -> None:
        self.opened_url: str | None = None
        self.properties: list[tuple[int, int]] = []
        self.released = False

    def set(self, property_id: int, value: int) -> None:
        self.properties.append((property_id, value))

    def open(self, stream_url: str) -> bool:
        self.opened_url = stream_url
        return True

    def read(self) -> tuple[bool, _FakeFrame]:
        return True, _FakeFrame()

    def release(self) -> None:
        self.released = True


class _FakeCv2:
    CAP_PROP_OPEN_TIMEOUT_MSEC = 1
    CAP_PROP_READ_TIMEOUT_MSEC = 2
    COLOR_BGR2RGB = 3
    INTER_AREA = 4

    def __init__(self, capture: _FakeCapture) -> None:
        self.capture = capture

    def VideoCapture(self) -> _FakeCapture:  # noqa: N802
        return self.capture

    def cvtColor(  # noqa: N802
        self, frame: _FakeFrame, color_conversion: int
    ) -> list[list[tuple[int, int, int]]]:
        assert color_conversion == self.COLOR_BGR2RGB
        return [
            [(blue, green, red) for red, green, blue in row]
            for row in frame.rows
        ]


def test_opencv_reader_gets_one_frame_sets_timeouts_and_releases_stream() -> None:
    capture = _FakeCapture()
    cv2 = _FakeCv2(capture)
    reader = OpenCvSnapshotReader(
        "rtsp://example.invalid/anonymous",
        analysis_width=64,
        clock=lambda: NOW,
        cv2_loader=lambda: cv2,
    )

    frame = reader.read_snapshot(timeout_seconds=3)

    assert frame.pixels[0][0] == (30, 20, 10)
    assert capture.properties == [(1, 3_000), (2, 3_000)]
    assert capture.opened_url == "rtsp://example.invalid/anonymous"
    assert capture.released is True
    assert "example.invalid" not in repr(reader)


def test_capabilities_do_not_claim_absolute_lux_or_camera_control() -> None:
    capabilities = EufyWeatherCapabilities()

    assert capabilities.read_only is True
    assert capabilities.snapshot_analysis is True
    assert capabilities.retains_images is False
    assert capabilities.absolute_lux is False
    assert capabilities.camera_control is False
    assert capabilities.e42_rtsp_wake_live_confirmed is False


@pytest.mark.parametrize(
    "roi",
    [
        (-0.1, 0, 0.5, 0.5),
        (0, 0, 0, 0.5),
        (0.8, 0, 0.3, 0.5),
    ],
)
def test_roi_must_fit_inside_frame(roi: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        NormalizedRoi(*roi)


def _observed(
    value: float | None,
    quality: Quality = Quality.GOOD,
) -> ObservedValue[float]:
    return ObservedValue(value=value, quality=quality)


def _energy_evidence(
    *,
    observed_at: str = "2026-07-27T00:59:00+00:00",
    generation_kw: float | None = 2.0,
    generation_quality: Quality = Quality.GOOD,
    window_minutes: int = 10,
    battery_soc: float | None = None,
    remaining_generation_kwh: float | None = None,
    remaining_load_kwh: float | None = None,
    forecast_quality: Quality = Quality.ESTIMATED,
) -> EnergyEvidence:
    return EnergyEvidence(
        observed_at=observed_at,
        rolling_generation_kw=_observed(generation_kw, generation_quality),
        generation_window_minutes=window_minutes,
        rated_ac_kw=4.95,
        battery_soc_percent=(
            _observed(battery_soc) if battery_soc is not None else None
        ),
        forecast_remaining_generation_kwh=(
            _observed(remaining_generation_kwh, forecast_quality)
            if remaining_generation_kwh is not None
            else None
        ),
        forecast_remaining_essential_load_kwh=(
            _observed(remaining_load_kwh, forecast_quality)
            if remaining_load_kwh is not None
            else None
        ),
    )


def test_energy_policy_skips_snapshot_when_sustained_generation_is_conclusive() -> None:
    decision = decide_snapshot_acquisition(
        _energy_evidence(generation_kw=3.5),
        now=NOW,
    )

    assert decision.action == SnapshotAction.SKIP_HIGH_GENERATION
    assert decision.reason == "sustained_generation_already_conclusive"
    assert decision.next_evaluation_minutes == 10
    assert decision.evidence_quality == Quality.GOOD


def test_energy_policy_does_not_skip_just_below_generation_threshold() -> None:
    decision = decide_snapshot_acquisition(
        _energy_evidence(generation_kw=3.4),
        now=NOW,
    )

    assert decision.action == SnapshotAction.ACQUIRE
    assert decision.next_evaluation_minutes == 10


def test_energy_policy_thresholds_are_runtime_configuration() -> None:
    decision = decide_snapshot_acquisition(
        _energy_evidence(generation_kw=3.4),
        policy=EnergyAwareSnapshotPolicy(high_generation_ratio=0.65),
        now=NOW,
    )

    assert decision.action == SnapshotAction.SKIP_HIGH_GENERATION


@pytest.mark.parametrize(
    ("observed_at", "quality", "window_minutes"),
    [
        ("2026-07-27T00:50:00+00:00", Quality.GOOD, 10),
        ("2026-07-27T00:59:00+00:00", Quality.STALE, 10),
        ("2026-07-27T00:59:00+00:00", Quality.GOOD, 5),
    ],
)
def test_untrusted_generation_never_suppresses_snapshot_as_abundant(
    observed_at: str,
    quality: Quality,
    window_minutes: int,
) -> None:
    decision = decide_snapshot_acquisition(
        _energy_evidence(
            observed_at=observed_at,
            generation_kw=4.95,
            generation_quality=quality,
            window_minutes=window_minutes,
        ),
        now=NOW,
    )

    assert decision.action == SnapshotAction.ACQUIRE
    assert decision.reason == "energy_evidence_incomplete_use_low_frequency"
    assert decision.next_evaluation_minutes == 60
    assert decision.evidence_quality == Quality.UNKNOWN


def test_winter_low_battery_pauses_camera_acquisition() -> None:
    winter_now = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)
    decision = decide_snapshot_acquisition(
        _energy_evidence(
            observed_at="2026-01-15T02:59:00+00:00",
            generation_kw=0.5,
            battery_soc=30,
        ),
        now=winter_now,
    )

    assert decision.action == SnapshotAction.PAUSE_ENERGY_SCARCITY
    assert decision.reason == "winter_battery_reserve_low"
    assert decision.evidence_quality == Quality.GOOD


def test_winter_forecast_deficit_pauses_with_estimated_quality() -> None:
    winter_now = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)
    decision = decide_snapshot_acquisition(
        _energy_evidence(
            observed_at="2026-01-15T02:59:00+00:00",
            generation_kw=0.5,
            remaining_generation_kwh=3,
            remaining_load_kwh=5,
        ),
        now=winter_now,
    )

    assert decision.action == SnapshotAction.PAUSE_ENERGY_SCARCITY
    assert decision.reason == "winter_forecast_energy_deficit"
    assert decision.evidence_quality == Quality.ESTIMATED


def test_energy_scarcity_pause_is_limited_to_winter_months() -> None:
    decision = decide_snapshot_acquisition(
        _energy_evidence(generation_kw=0.5, battery_soc=20),
        now=NOW,
    )

    assert decision.action == SnapshotAction.ACQUIRE


def test_paused_camera_uses_hysteresis_before_resuming() -> None:
    winter_now = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)
    evidence = _energy_evidence(
        observed_at="2026-01-15T02:59:00+00:00",
        generation_kw=0.5,
        battery_soc=35,
    )

    still_paused = decide_snapshot_acquisition(
        evidence,
        now=winter_now,
        previously_paused=True,
    )
    resumed = decide_snapshot_acquisition(
        _energy_evidence(
            observed_at="2026-01-15T02:59:00+00:00",
            generation_kw=0.5,
            battery_soc=40,
        ),
        now=winter_now,
        previously_paused=True,
    )

    assert still_paused.action == SnapshotAction.PAUSE_ENERGY_SCARCITY
    assert still_paused.reason == "recovery_hysteresis_not_satisfied"
    assert resumed.action == SnapshotAction.ACQUIRE
