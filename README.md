# hedp

Python project for HEDP.

## Setup

Create and install into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Set these environment variables:

- `HEDP_FUSIONSOLAR_BASE_URL`
- `HEDP_FUSIONSOLAR_STATION_DN`
- `HEDP_FUSIONSOLAR_USERNAME`
- `HEDP_FUSIONSOLAR_PASSWORD`
- `HEDP_DATABASE_PATH`

Collect today's data:

```bash
hedp collect
```

Collect a date range:

```bash
hedp collect --start 2026-07-01 --end 2026-07-03
```

Run daily:

```bash
hedp collect
```

Check missing dates:

```bash
hedp missing --start 2026-01-01 --end 2026-07-20
```

Backfill missing dates:

```bash
hedp backfill-missing --start 2026-01-01 --end 2026-07-20
```

Check saved record quality:

```bash
hedp quality --start 2026-01-01 --end 2026-07-20
```

The exit code is 0 when no problems are found and 1 when quality issues are
found.

Create a manual backup:

```bash
hedp backup
```

Backups are saved in `backups/` next to the database. Copy the SQLite file
to another device to migrate the data.

HEDP is OS-independent. Use the operating system's scheduler to run
`hedp collect` automatically.

## macOS automatic collection

Install the launchd job:

```bash
scripts/install_macos_launchd.sh
```

Uninstall it:

```bash
scripts/uninstall_macos_launchd.sh
```

The job runs `hedp collect` and then `hedp backup` every day at 3:00 AM.
Backups are saved in `backups/`, and the latest 30 are retained. If the Mac
is asleep, launchd may run it after the Mac wakes. Check or repair missed
dates with `hedp missing` and `hedp backfill-missing`.

Logs are stored in `~/Library/Logs/hedp/collect.out.log` and
`~/Library/Logs/hedp/collect.err.log`.

HEDP itself remains OS-independent; only this automatic execution setup is
macOS-specific.
