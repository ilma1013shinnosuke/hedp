from pathlib import Path


GAS_ROOT = Path("cloud/gas/fusionsolar")


def test_gas_source_has_manifest_and_required_modules():
    expected = {
        "appsscript.json",
        "Config.gs",
        "HttpSession.gs",
        "Queue.gs",
        "Collectors.gs",
        "Triggers.gs",
        "README.md",
    }
    assert expected <= {item.name for item in GAS_ROOT.iterdir()}


def test_gas_source_contains_no_household_values_or_login_password_fields():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in GAS_ROOT.iterdir()
        if path.suffix in {".gs", ".json"}
    )
    assert "NE=" not in source
    assert "FUSIONSOLAR_PASSWORD" not in source
    assert "FUSIONSOLAR_USERNAME" not in source


def test_gas_queue_has_deduplication_and_attempt_limit():
    source = (GAS_ROOT / "Queue.gs").read_text(encoding="utf-8")
    assert "payload_sha256" in source
    assert "HEDP_MAX_ATTEMPTS_PER_SOURCE_DATE = 3" in source
    assert 'status: "duplicate"' in source
