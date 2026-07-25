import importlib.util
from pathlib import Path
import stat


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "modbus_continuity", ROOT / "scripts" / "modbus_continuity.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_private_continuity_state_resets_epoch_for_gap_and_reboot(tmp_path, monkeypatch):
    path = tmp_path / "private" / "modbus-state.json"
    monkeypatch.setenv("SUMICORE_MODBUS_CONTINUITY_STATE_PATH", str(path))
    moments = iter((100.0, 400.0, 1101.0, 1200.0))
    monkeypatch.setattr(module.time, "time", lambda: next(moments))
    markers = iter(("boot-a", "boot-a", "boot-a", "boot-b"))
    monkeypatch.setattr(module, "_boot_marker", lambda: next(markers))

    initial_id, initial_reason = module.prepare(interval_seconds=300, gap_multiplier=2)
    continuous_id, continuous_reason = module.prepare(interval_seconds=300, gap_multiplier=2)
    gap_id, gap_reason = module.prepare(interval_seconds=300, gap_multiplier=2)
    reboot_id, reboot_reason = module.prepare(interval_seconds=300, gap_multiplier=2)

    assert initial_reason == "initial"
    assert continuous_reason == "continuous"
    assert gap_reason == "scheduling_gap"
    assert reboot_reason == "boot_changed"
    assert initial_id == continuous_id
    assert gap_id != initial_id
    assert reboot_id != gap_id
    assert len(reboot_id) == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_continuity_state_rejects_a_symlink(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.write_text("{}")
    path = tmp_path / "modbus-state.json"
    path.symlink_to(target)
    monkeypatch.setenv("SUMICORE_MODBUS_CONTINUITY_STATE_PATH", str(path))

    try:
        module.prepare(interval_seconds=300, gap_multiplier=2)
    except RuntimeError as error:
        assert "unsafe" in str(error)
    else:
        raise AssertionError("unsafe state path was accepted")


def test_missing_boot_evidence_breaks_the_continuity_identifier(tmp_path, monkeypatch):
    path = tmp_path / "private" / "modbus-state.json"
    monkeypatch.setenv("SUMICORE_MODBUS_CONTINUITY_STATE_PATH", str(path))
    moments = iter((100.0, 400.0, 700.0))
    monkeypatch.setattr(module.time, "time", lambda: next(moments))
    markers = iter(("boot-a", None, "boot-b"))
    monkeypatch.setattr(module, "_boot_marker", lambda: next(markers))

    initial_id, _ = module.prepare(interval_seconds=300, gap_multiplier=2)
    unavailable_id, unavailable_reason = module.prepare(
        interval_seconds=300, gap_multiplier=2
    )
    recovered_id, recovered_reason = module.prepare(
        interval_seconds=300, gap_multiplier=2
    )

    assert unavailable_reason == "boot_evidence_unavailable"
    assert recovered_reason == "boot_evidence_recovered"
    assert len({initial_id, unavailable_id, recovered_id}) == 3
