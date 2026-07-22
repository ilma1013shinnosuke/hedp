# hedp

HEDP is a long-lived household energy data platform. See [PROJECT.md](PROJECT.md)
for its purpose and principles, [SPECIFICATION.md](SPECIFICATION.md) for the
current technical contract, and
[FusionSolar knowledge](docs/integrations/fusionsolar/README.md) for verified vendor API
details and unknowns.

ディレクトリと命名は [directory policy](docs/directory-policy.md)、現在の
ファイル対応は [current layout](docs/current-layout.md)、秘密情報と実データは
[security policy](docs/security-policy.md) を参照してください。

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
Battery DC collection uses the confirmed battery DeviceDN and Signal IDs by
default. `HEDP_FUSIONSOLAR_BATTERY_DN` and
`HEDP_FUSIONSOLAR_BATTERY_SIGIDS` are optional overrides.

## Main commands

```bash
hedp collect
hedp collect --start 2026-07-01 --end 2026-07-03
hedp collect-energy-balance --start 2026-07-19 --end 2026-07-19
hedp collect-device-realtime
hedp collect-battery-dc
hedp collect-alarms-current
hedp collect-alarms-history --start 2026-07-19 --end 2026-07-20
hedp quality-battery-dc
hedp diagnose-battery-dc
hedp quality-alarms
hedp diagnose-alarms
hedp build-energy-balance-records --start 2026-07-19 --end 2026-07-19
hedp missing --start 2026-01-01 --end 2026-07-20
hedp backfill-missing --start 2026-01-01 --end 2026-07-20
hedp backfill-energy-balance --start 2026-01-01 --end 2026-07-20
hedp quality --start 2026-01-01 --end 2026-07-20
hedp quality-diagnose --start 2026-01-01 --end 2026-07-20
hedp quality-energy-balance --start 2026-07-19 --end 2026-07-19
hedp diagnose-device-realtime
hedp backup
hedp daily-health --verbose
hedp daily-health --json
hedp switchbot devices refresh
hedp switchbot collect --dry-run
hedp switchbot collect
hedp switchbot import inspect runtime/import/switchbot
hedp switchbot import run runtime/import/switchbot --dry-run
hedp switchbot import report
hedp switchbot observations latest
hedp switchbot gaps
hedp switchbot hourly rebuild
hedp import-fusionsolar-reports runtime/import2 --dry-run
```

Quality commands that report issue status exit with 0 when no issue is found
and 1 when issues are found; diagnostic commands exit with 0 after completion.
Backups are stored in `backups/` next to the database. The daily job compresses
them and retains the latest generation by default. Copying the SQLite file to
another device migrates the data.

## macOS automatic operation

```bash
scripts/install_macos_launchd.sh
scripts/install_macos_device_realtime_launchd.sh
scripts/install_macos_equipment_launchd.sh
scripts/install_macos_daily_health_launchd.sh
scripts/install_macos_switchbot_launchd.sh
```

The daily job runs station collection, detects and refetches missing station
and energy-balance days in a rolling 30-day window, rebuilds energy-balance
Records, runs both quality checks, and backs up from 03:00. Each command has a
15-minute timeout, and every database-writing job shares one lock to prevent
cross-job SQLite writes. Set
`HEDP_DAILY_COMMAND_TIMEOUT_SECONDS` or `HEDP_DAILY_BACKFILL_DAYS` to tune the
defaults. Before creating a backup, existing SQLite backups are compressed and
old generations are removed so there is room for the new snapshot. The new
snapshot is then compressed too; one generation is retained by default. Set
`HEDP_BACKUP_RETENTION_COUNT` to retain more. The separate
realtime job collects device snapshots, battery DC, and current alarms every
five minutes with one shared FusionSolar session. The independent equipment
job also collects battery DC daily at 03:10 as a daily recovery/health
snapshot. Logs are stored with mode `0600` under
`~/Library/Logs/hedp/`; macOS-specific behavior remains in `scripts/`.

The read-only daily health check runs independently at 03:20. It checks recent
collection coverage and gaps, previous-day daily data and derived Records,
backup freshness, and SQLite integrity. Exit status is 0 for healthy, 1 for
warnings, and 2 when the check cannot run or the database is unhealthy. It
does not repair data. Mac sleep gaps of 15 minutes or more are reported rather
than hidden. JSON logs are written to
`~/Library/Logs/hedp/daily-health.out.log`, with execution errors in
`daily-health.err.log`. When an issue is reported, rerun
`hedp daily-health --verbose` and the existing quality/diagnose commands.

SwitchBot uses an independent Open API v1.1 adapter. Credentials remain in
the Git-ignored, mode-0600 `.env`; they are not copied into launchd plists or
SQLite. The hourly job runs at minute 05, retains complete status responses,
and does not fabricate observations missed during Mac sleep. Daily health uses
hourly criteria and treats empty Hub/Remote bodies as successful communication.

Historical SwitchBot CSV/XLSX exports are inspected before import and streamed
without hourly thinning. Naive timestamps are interpreted as Asia/Tokyo,
exact duplicates are skipped, differing values at one timestamp are retained
and audited, and missing periods are never interpolated. Inspect and dry-run
reports must be checked before a real import.
Historical export files are not part of the repository. The current deployment
imported the available history on 2026-07-21; repeating the import inserted no
additional observations. Future deployments still require the original files.

The missing `発電所レポート_2024-01.xlsx` was downloaded again and imported on
2026-07-21 after a zero-conflict dry run. The import added 31 audited days and
492 Records; an immediate repeat dry run reported all 492 values as exact
duplicates. The normal station and energy-balance API backfills remain
independent of this legacy report archive.

Uninstall the daily job with `scripts/uninstall_macos_launchd.sh`.

## Development checks

```bash
pytest
ruff check .
```
