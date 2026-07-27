from hedp.operations.switchbot_strip_light_live_trial_runner import (
    run_from_environment,
)


def test_missing_private_runtime_configuration_is_safe():
    result = run_from_environment({})

    assert result == {
        "target_alias": "strip-light-3",
        "reason": "private_runtime_configuration_incomplete",
        "change_attempted": False,
        "restore_attempted": False,
        "persisted": False,
    }
