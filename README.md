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
