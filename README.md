# hedp

HEDP is a long-lived household energy data platform. See [PROJECT.md](PROJECT.md)
for its purpose and principles, [SPECIFICATION.md](SPECIFICATION.md) for the
current technical contract, and
[FusionSolar knowledge](docs/KNOWLEDGE/FusionSolar.md) for verified vendor API
details and unknowns.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Set `HEDP_FUSIONSOLAR_BASE_URL`, `HEDP_FUSIONSOLAR_STATION_DN`,
`HEDP_FUSIONSOLAR_USERNAME`, `HEDP_FUSIONSOLAR_PASSWORD`, and
`HEDP_DATABASE_PATH`. Realtime collection also requires the ordered,
comma-separated `HEDP_FUSIONSOLAR_DEVICE_DNS` value.

## Main commands

```bash
hedp collect
hedp collect --start 2026-07-01 --end 2026-07-03
hedp collect-energy-balance --start 2026-07-19 --end 2026-07-19
hedp collect-device-realtime
hedp build-energy-balance-records --start 2026-07-19 --end 2026-07-19
hedp missing --start 2026-01-01 --end 2026-07-20
hedp backfill-missing --start 2026-01-01 --end 2026-07-20
hedp quality --start 2026-01-01 --end 2026-07-20
hedp quality-diagnose --start 2026-01-01 --end 2026-07-20
hedp quality-energy-balance --start 2026-07-19 --end 2026-07-19
hedp diagnose-device-realtime
hedp backup
```

Quality commands that report issue status exit with 0 when no issue is found
and 1 when issues are found; diagnostic commands exit with 0 after completion.
Backups are stored in `backups/` next to the database, with the latest 30 kept
by the daily job. Copying the SQLite file to another device migrates the data.

## macOS automatic operation

```bash
scripts/install_macos_launchd.sh
scripts/install_macos_device_realtime_launchd.sh
```

The daily job runs station collection, previous-day energy-balance collection
and Record generation, quality checks, and backup from 03:00. The separate
device-realtime job runs every five minutes. Logs are stored under
`~/Library/Logs/hedp/`; macOS-specific behavior remains in `scripts/`.

Uninstall the daily job with `scripts/uninstall_macos_launchd.sh`.

## Development checks

```bash
pytest
ruff check .
```
