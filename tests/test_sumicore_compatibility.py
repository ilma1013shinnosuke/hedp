from hedp.main import cli as legacy_cli
from sumicore.main import cli


def test_sumicore_cli_uses_existing_implementation_during_migration():
    assert cli is legacy_cli
