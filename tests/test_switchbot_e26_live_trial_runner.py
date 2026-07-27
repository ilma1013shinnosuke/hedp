from hedp.adapters.switchbot.e26_live_trial_runner import run_from_environment


def test_runner_fails_closed_without_credentials(monkeypatch):
    monkeypatch.delenv("SWITCHBOT_TOKEN", raising=False)
    monkeypatch.delenv("SWITCHBOT_SECRET", raising=False)

    summary = run_from_environment()

    assert summary["reason"] == "credentials_unavailable"
    assert summary["command_requests"] == 0
    assert summary["stopped_after_e26"] is True
