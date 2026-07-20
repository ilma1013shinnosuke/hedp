# HEDP Specification

## Architecture

```text
API -> Collector -> RawData
RawData -> RecordBuilder -> Record
```

Application performs orchestration and Storage performs persistence. There is
no Observation layer, and HEDP does not introduce UUIDs.

## RawData

- RawData is the immutable Source of Truth.
- `payload` stores the complete API response without conversion.
- `timestamp` is the acquisition time.
- `target_date` is used only by APIs that address a date.
- `metadata` stores request context, such as a target device, that is outside
  the response payload.
- HEDP does not insert private keys into `payload`.
- JSON without the optional metadata field remains readable for backward
  compatibility.

## Record

- A Record is normalized analysis data reproducible from RawData.
- It contains `source`, `timestamp`, `metric`, `value`, and `unit`; `source`
  provides the existing provenance mechanism.
- Rebuilding does not add exact duplicate Records.
- Unconfirmed units are not inferred.

## Collector rules

- Vendor-specific behavior is isolated within Collectors.
- Credentials and complete API responses are not written to normal logs.
- Independent targets continue when one target fails, where the API permits.
- An API is not implemented until its request and response have been observed.

## Storage rules

- SQLite is the persistence store and existing databases remain compatible.
- RawData is not normally deleted, overwritten, or mutated.
- Realtime snapshots with equal payloads are retained when their acquisition
  timestamps differ.
- Record regeneration prevents exact duplicates.

## Time rules

- Persisted timestamps use UTC by default.
- Display dates and requested dates are interpreted in Asia/Tokyo.
- FusionSolar energy-balance `xAxis` values are interpreted in Asia/Tokyo and
  normalized to UTC.
- Daily scheduled work uses Asia/Tokyo dates.

## Runtime

The core supports macOS and Windows. launchd integration is confined to
`scripts/`; no OS-specific behavior is placed in the core. Runtime operation
does not depend on AI, ChatGPT, or Codex.

## Current scheduled collection

- `device-realtime`: every five minutes
- Previous-day `energy-balance`: daily at 03:00
- `station-kpi`: existing daily collection at 03:00
- Backup: after the daily collection and quality steps
- Battery DC: daily at 03:10; confirmed API, configured Signal IDs
- Other equipment/configuration/Signal APIs: planned for 03:10; unconfirmed
- Current alarms: every five minutes
- Alarm history: explicit date-range collection

## Quality requirements

Station KPI quality checks report exact duplicates, invalid values, unexpected
metrics and units, missing required metrics, irregular same-day intervals, and
summary timestamps. Current station data expects four required metrics and a
60-minute interval; `buyPower` is optional.

Energy-balance quality checks validate 288 `xAxis` points, five-minute order,
array lengths, target-date agreement, missing-marker and valid-value counts,
daily fields, RawData without derived Records, and idempotent Record generation.
Device-realtime diagnostics report total and per-device snapshot counts,
latest timestamps, and gaps greater than ten minutes. API failures are logged
for the run but are not currently persisted as database events.

Battery DC quality reports response structure, module coverage, empty-module
responses, and latest snapshots. Alarm quality reports response structure,
API success flags, configured-device CURRENT coverage, and observed hit counts.
The corresponding diagnose commands always return their aggregate details
without changing data.

## Security

- Credentials, databases, backups, logs, and environment files are not
  committed to Git.
- Cookie, CSRF token, session ID, and password values are not displayed or
  logged.
- Generated launchd plist files contain runtime credentials only when required
  by the existing installation method and use mode `0600`; they are outside
  the repository.
- Operational logs are checked for accidental secret disclosure.
