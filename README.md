# SumiCore

SumiCore（旧HEDP）は、家庭の事実を長期保存し、分析・判断・安全な操作へつなぐ基盤です。
機器を置き換える必須制御装置ではなく、停止しても機器自身の基本機能と物理操作が
継続する非必須の拡張層とします。
See [PROJECT.md](PROJECT.md)
for its purpose and principles, [SPECIFICATION.md](SPECIFICATION.md) for the
current technical contract, and
[FusionSolar knowledge](docs/integrations/fusionsolar/README.md) for verified vendor API
details and unknowns.

設計の4区分は [①情報収集](docs/01_collection.md)、
[②情報蓄積](docs/02_storage.md)、[③情報利用・判断](docs/03_intelligence.md)、
[④操作・実行](docs/04_execution.md) を参照してください。④の正式な共通契約は
[共通Execution層 基本設計](docs/execution-contract.md)、採用理由は
[決定記録002](docs/decisions/002_common_execution_layer.md)にあります。ディレクトリと命名は
[directory policy](docs/directory-policy.md)、現在の
ファイル対応は [current layout](docs/current-layout.md)、秘密情報と実データは
[security policy](docs/security-policy.md) を参照してください。
現状の確認結果と未解決riskは
[security review](docs/security-review.md)にまとめています。
システム全体の目的と非目標は [SumiCoreの思想](docs/system-philosophy.md)、
保存期間・粒度・可逆圧縮・削除条件は
[データ保存共通方針](docs/data-retention-policy.md)にあります。
実運用から見つかった改善点と実施順は
[SumiCore全体レビュー](docs/system-review.md)にまとめています。
新しい機器の調査、読み取り・操作の分離、段階導入、廃止は
[Adapter lifecycle](docs/adapter-lifecycle.md)を参照してください。
家庭固有値の置き場所は[local configuration](docs/local-configuration.md)、Python更新は
[Python runtime](docs/python-runtime.md)、改名は
[name and renaming](docs/name-and-renaming.md)を参照してください。

## Setup

```bash
python3.12 scripts/check_python_runtime.py
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m pip install pytest ruff
```

Python 3.13.14では安全強化により先頭が`__`の`.pth`が読み飛ばされるため、setuptoolsが
生成するeditable installに依存しない。開発時も通常wheel形式で入れ、ソース変更後は
`python -m pip install --no-deps .`で更新する。

macOS付属のPython 3.9（LibreSSL版）は使用しません。更新と安全な切替は
[`docs/python-runtime.md`](docs/python-runtime.md)を参照してください。

Set `HEDP_FUSIONSOLAR_BASE_URL`, `HEDP_FUSIONSOLAR_STATION_DN`,
`HEDP_FUSIONSOLAR_USERNAME`, `HEDP_FUSIONSOLAR_PASSWORD`, and
`HEDP_DATABASE_PATH`. Realtime collection also requires the ordered,
comma-separated `HEDP_FUSIONSOLAR_DEVICE_DNS` value.
Battery DC collection also requires `HEDP_FUSIONSOLAR_BATTERY_DN` and
`HEDP_FUSIONSOLAR_BATTERY_SIGIDS`; household-specific identifiers have no
source-code defaults. SwitchBot filename mappings and room history are read
from the Git-ignored JSON file named by
`HEDP_SWITCHBOT_HOUSEHOLD_CONFIG_PATH`. A value-free example is under
`config/examples/`.

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
hedp import-fusionsolar-gas-queue runtime/import/fusionsolar-gas --inspect
hedp import-fusionsolar-gas-queue runtime/import/fusionsolar-gas --dry-run
```

Quality commands that report issue status exit with 0 when no issue is found
and 1 when issues are found; diagnostic commands exit with 0 after completion.
Backups are stored in `backups/` next to the database. The daily job compresses
them and retains the latest generation by default. Copying the SQLite file to
another device migrates the data.

Database backups are created atomically. Before copying, SumiCore requires
free space for the current database plus a safety reserve. It writes to a
mode-0600 hidden `.partial` file, promotes that file to the dated `.db` name
only after SQLite finishes successfully, and removes partial files when an
ordinary error occurs. A failed copy is therefore not presented as a valid
backup and does not replace the previous generation. Compressed backups also
remain mode `0600`. If a hard process termination prevents normal cleanup,
the next daily job removes generated partial files older than one hour; recent
partial files are left alone to avoid interfering with active work.
容量不足時の確認、再実行、削除判断は
[`docs/backup-capacity-recovery.md`](docs/backup-capacity-recovery.md) に従います。

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
15-minute timeout, and every database job shares one lock to prevent
cross-job SQLite conflicts. Set
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

All five scheduled jobs also append a separate anonymous operational journal.
It records only the UTC date, fixed job/outcome/error categories, coarse
duration, and a daily read-only capacity probe. It contains no payload,
device identifier, database path, exception text, or exact execution time.
The default is `~/.local/state/sumicore/operational-metrics.jsonl`, mode
`0600`, with a 1 MiB limit and two rotated generations. Set
`SUMICORE_OPERATIONAL_METRICS_PATH` to an absolute path whose directory is
private. Details are in
[`docs/operational-metrics.md`](docs/operational-metrics.md).

The read-only daily health check runs independently at 04:10. It checks recent
collection coverage and gaps, ten derived Records for every checked
FusionSolar Modbus snapshot, previous-day daily data and derived Records,
backup freshness, and SQLite integrity. Exit status is 0 for healthy, 1 for warnings,
and 2 when the check cannot run or the database is unhealthy. It does not
repair data. Mac sleep gaps of 15 minutes or more are reported rather than
hidden. JSON logs are written to
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
