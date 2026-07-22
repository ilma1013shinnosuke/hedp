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
    assert "SUMICORE_MAX_ATTEMPTS_PER_SOURCE_DATE = 3" in source
    assert 'status: "duplicate"' in source


def test_gas_collection_has_concurrency_and_response_size_limits():
    collectors = (GAS_ROOT / "Collectors.gs").read_text(encoding="utf-8")
    session = (GAS_ROOT / "HttpSession.gs").read_text(encoding="utf-8")
    assert "LockService.getScriptLock" in collectors
    assert "tryLock(1000)" in collectors
    assert "MAX_RESPONSE_BYTES = 10 * 1024 * 1024" in session
    assert "fusionSolarResponseHeader_" in session
    assert "reportFusionSolarAuthenticationHealthy_" in session


def test_gas_trigger_creates_replacement_before_deleting_previous_trigger():
    source = (GAS_ROOT / "Triggers.gs").read_text(encoding="utf-8")
    assert source.index(".create()") < source.index("ScriptApp.deleteTrigger")


def test_gas_base_url_is_limited_to_https_origin():
    source = (GAS_ROOT / "Config.gs").read_text(encoding="utf-8")
    assert "HTTPS origin without a path" in source
    assert "SUMICORE_QUEUE_FOLDER_ID" in source
