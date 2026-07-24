# SumiCore Specification

## Architecture

```text
① Collection -> ② Storage -> ③ Intelligence -> ④ Execution
       |              |
       v              v
    RawData         Record / current / history / event
```

The four responsibilities are the long-term architecture. Only directories
with current implementations are created. Application currently orchestrates
existing collection and quality workflows, and Storage performs persistence.
No additional Observation layer or UUID mechanism is introduced merely for a
possible future need.

## RawData

- RawData is the immutable Source of Truth.
- `payload` stores the complete API response without conversion.
- `timestamp` is the acquisition time.
- `target_date` is used only by APIs that address a date.
- `metadata` stores request context, such as a target device, that is outside
  the response payload.
- SumiCore does not insert private keys into `payload`.
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
- SwitchBot uses independent normalized tables for device identity, API-name
  history, location history, observations, import audits, conflicts, gaps, and
  reproducible hourly summaries.
- SwitchBot historical exports retain second-resolution source values. Exact
  duplicates are removed idempotently; conflicting values at one timestamp
  are retained and audited. Missing data is not interpolated.

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

## Equipment autonomy contract

Equipment autonomy is the default design policy, not a blanket prohibition on
SumiCore-controlled or SumiCore-dependent functions. SumiCore may be the
control owner when the equipment has no equivalent function or cross-equipment
coordination has a clear benefit, provided the exception is documented.

- Collection, storage, intelligence, and execution failures must not disable
  vendor safety functions, physical controls, or the equipment's standard
  schedules.
- Production execution must not replay a saved state or unfinished command
  after startup. It must first read the current equipment state and validate
  its freshness and quality.
- Every production automation must declare its control owner, expiry,
  confirmation method, and behavior when SumiCore is unavailable.
- A function that exists only in SumiCore must be labelled as SumiCore-dependent
  and document its reason, benefit, manual override, expiry, confirmation
  method, and safe fallback or explicit stopped state.
- Duplicate schedules or continuously competing rules across SumiCore and the
  equipment are not allowed.
- Safety-critical household behavior must not have SumiCore as its only path.

## Execution contract

The common Execution design is adopted, but no production Execution package or
database migration exists yet. Its normative design is
[`docs/execution-contract.md`](docs/execution-contract.md).

- Intelligence and users request a vendor-neutral immutable Intent.
- Intelligence exclusively owns value judgement: comparing economy, comfort,
  health, safety, equipment protection, and current user direction, and
  choosing information, proposal, or pre-authorized automation.
- Execution does not repeat or modify that judgement. Its ExecutionGate checks
  authorization, pre-approval, expiry, current-state freshness, target
  capability, duplicate suppression, equipment limits, and consistency with
  current user direction.
- Execution then owns bounded retry, fan-out, dispatch, verification, and audit.
- Adapters own vendor translation, transport, error mapping, and the read
  primitive used for verification.
- Dispatch acknowledgement is not proof that equipment reached the desired
  state.
- Processing Phase and terminal Outcome are separate. `unknown` and `partial`
  are valid outcomes and must not be converted to success.
- Retry policy depends on command semantics. Trigger and configuration
  operations are not blindly retried.
- Multi-target work uses parent and child operations; cross-vendor atomicity
  and automatic rollback are not assumed.
- Startup and reconnect enter a syncing state. Saved state and unfinished
  commands are not replayed.
- Shadow Mode never dispatches and never reports a completed real operation.
- Production writes are introduced in stages, beginning with one low-risk,
  single-target, absolute-state capability.

## Current scheduled collection

- `device-realtime`, Battery DC, and current alarms: every five minutes with a
  shared client/session and independent failure handling
- Previous-day `energy-balance`: daily at 03:00
- `station-kpi`: existing daily collection at 03:00
- Backup: after the daily collection and quality steps
- Battery DC: also daily at 03:10 in an independent job so a failure or outage
  in the five-minute job does not remove the daily health snapshot
- Other equipment/configuration/Signal APIs: planned for 03:10; unconfirmed
- Current alarms: every five minutes
- Alarm history: explicit date-range collection
- Daily health: read-only operational check daily at 04:10, after the daily
  collection and backup normally finish
- SwitchBot status snapshots: hourly at minute 05 in an independent job

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
responses, latest snapshots, and Signal ID-set changes. Alarm quality reports
response structure, API success flags, configured-device CURRENT coverage,
five-minute gaps, daily HISTORY counts, pagination consistency, and observed
hit counts.
The corresponding diagnose commands always return their aggregate details
without changing data.

Daily health reuses the existing quality and diagnostic results. In one
read-only run it checks the current RawData sources, configured device and
battery-module coverage, 15-minute-or-greater gaps in five-minute collection,
every checked Modbus snapshot's ten derived Records, previous-day daily data,
energy-balance shape and Records, alarm-history device coverage, backup age
under 48 hours, and SQLite `integrity_check`. Thresholds are defined together
in the daily-health service. Status is healthy, warning, or critical with exit
codes 0, 1, and 2 respectively. It never repairs data.
Results are logged by the macOS 04:10 launchd job and are not persisted in a
new table or RawData source; persistent health history can be added later if
needed.

SwitchBot daily health checks enabled devices with hourly criteria: 24-hour
coverage, a 2.5-hour latest/gap threshold, API failures, inventory changes,
batteries at or below 20%, and the combined zero temperature/humidity/battery
condition. Null CO2 on unsupported devices and successful empty Hub/Remote
bodies are normal.

## SwitchBot

Open API v1.1 inventory and status responses are collected without request
headers or credentials. Complete response JSON is retained beside normalized
values. Plug Mini (JP) uses the official units: voltage in V,
`electricCurrent` in mA, `weight` in W, and `electricityOfDay` in minutes.
Unknown devices and fields remain valid through the raw response.

Historical timestamps are local Asia/Tokyo times and normalize to UTC while
retaining local timestamps and raw source rows. Exported absolute humidity,
dew point, and VPD are source values rather than recalculated replacements.
For API snapshots where temperature, humidity, and battery are all zero,
temperature and humidity normalize to null, battery remains zero, status is
`battery_depleted_or_unavailable`, and raw JSON remains unchanged.

## Security

- Credentials, databases, backups, logs, and environment files are not
  committed to Git.
- Cookie, CSRF token, session ID, and password values are not displayed or
  logged.
- Generated launchd plist files contain runtime credentials only when required
  by the existing installation method and use mode `0600`; they are outside
  the repository.
- Operational logs are checked for accidental secret disclosure.
