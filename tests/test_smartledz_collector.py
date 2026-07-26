from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from hedp.adapters.smartledz import (
    ReadCommand,
    SmartLedzReadOnlyCollector,
    SmartLedzReadTargets,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "smartledz"
    / "confirmed_read_resources_v1.json"
)
NOW = datetime.fromisoformat("2026-07-26T12:00:00+09:00")


class FakeTransport:
    def __init__(self, fixture: dict[str, object]) -> None:
        self.fixture = fixture
        self.commands: list[str] = []

    def read(self, command: ReadCommand) -> object:
        self.commands.append(command.command)
        return {
            "GroupList": self.fixture["group_list"],
            "GroupGet": self.fixture["group_detail"],
            "DeviceList": self.fixture["sensor_list"],
            "GroupScheduleGet": self.fixture["schedule_detail"],
            "DeviceSensorSwitchGetLuxValues": self.fixture["illuminance"],
        }[command.command]


def test_collector_uses_only_confirmed_reads_and_removes_source_ids() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FakeTransport(fixture)
    collector = SmartLedzReadOnlyCollector(
        transport,
        SmartLedzReadTargets(
            gateway_id=11,
            group_aliases={101: "living"},
            scene_aliases={201: "night"},
            schedule_aliases={301: "weekday"},
            device_aliases={401: "living-main"},
            sensor_aliases={501: "living-sensor"},
            schedule_groups={301: 101},
        ),
        clock=lambda: NOW,
    )

    raw = collector.collect()
    rendered = raw.to_json()

    assert transport.commands == [
        "GroupList",
        "GroupGet",
        "DeviceList",
        "GroupScheduleGet",
        "DeviceSensorSwitchGetLuxValues",
    ]
    assert raw.payload["groups"]["items"][0]["power"] is True
    assert raw.payload["group_details"][0]["scenes"]["items"][0][
        "target_ref"
    ] == "night"
    assert raw.payload["schedules"][0]["items"][0]["steps"][0][
        "scene_ref"
    ] == "night"
    assert raw.payload["illuminance"][0]["value"] == 420
    assert raw.metadata["group_count"] == 1
    assert len(raw.payload["evidence_sha256"]) == 5
    for source_value in ("101", "201", "301", "401", "501", "anonymous"):
        assert source_value not in rendered


def test_targets_reject_cross_reference_without_group_alias() -> None:
    try:
        SmartLedzReadTargets(
            gateway_id=11,
            group_aliases={},
            scene_aliases={201: "night"},
            schedule_aliases={301: "weekday"},
            device_aliases={},
            sensor_aliases={},
            schedule_groups={301: 101},
        )
    except ValueError as error:
        assert "group alias" in str(error)
    else:
        raise AssertionError("invalid schedule group was accepted")
