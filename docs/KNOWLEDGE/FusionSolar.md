# FusionSolar API knowledge inventory

## Scope and evidence levels

This document records only behavior supported by the current Python code,
stored responses, or the observed GAS-era workbook. It does not carry forward
the GAS architecture.

Every API uses one of these current status labels:

- **candidate**: a name or intended capability exists, but the communication
  contract has not been observed.
- **devtools-observed**: method, request, or response was captured from the
  FusionSolar browser application, but no Python collector is implemented.
- **implementation-confirmed**: a Python collector exists and its communication
  contract is covered without external communication in tests.
- **live-confirmed**: the current Python implementation has successfully called
  the live FusionSolar service and stored the returned response as RawData.

Older GAS workbook evidence is retained as supporting evidence, but is not a
status label for the current implementation.

The requested legacy sources `00_Config.js`,
`01_FusionSolarConnector.js`, `02_DeviceCollector.js`,
`03_EnergyCollector.js`, `04_StationCollector.js`, and
`FUSIONSOLAR_STATUS.md` were not present in the repository, Git history, local
filesystem, or connected Drive search. Consequently, no GAS function name is
claimed unless it is present in another observed artifact.

Observed supporting artifact: Google Sheet `10_HEMSデータベース`, especially
tabs `01_変更履歴`, `02_GAS設定`, `12_RAW_FusionSolar_5分`,
`13_RAW_FusionSolar_時間`, `14_RAW_FusionSolar_デバイス`,
`20_MST_Device`, `21_MST_Signal`, `22_CUR_FusionSolar_蓄電池`,
`23_CUR_FusionSolar_PCS`, `24_SPEC_FusionSolar_API`,
`96_QA_FusionSolar_5分`, and `99_取込履歴`.

## 1. Authentication

### Confirmed route

The current client opens the station application URL and uses this sequence:

1. `GET /unisso/login.action`, with an encoded
   `/unisess/v1/auth?service=...` service value.
2. `GET /unisso/pubkey`.
3. `POST /unisso/v3/validateUser.action` when encryption is enabled, otherwise
   `POST /unisso/v2/validateUser.action`.
4. Follow the returned authentication transition URL and redirects.
5. `GET /unisess/v1/auth/session` and extract `csrfToken`.

With encryption enabled, the password is URL-encoded and encrypted in blocks
with RSA OAEP/SHA-384; the public-key version is appended. The validation body
contains `organizationName`, `username`, encrypted `password`, empty
`verifycode`, and `multiRegionName`. The request also includes `decision=1`, a
millisecond timestamp, and a nonce.

Evidence: `src/hedp/fusionsolar_client.py` —
`FusionSolarClient.login`, `_encrypt_password`, `_follow_redirects`,
`_get_session_data`; `tests/test_fusionsolar_client.py` —
`test_login_uses_verified_requests_and_follows_redirects` and
`test_encrypt_password_url_encodes_chunks_and_appends_version`. The workbook
tab `02_GAS設定` records `AUTH_MODE=automatic_rsa_oaep_sha384` and successful
login/data timestamps, but the GAS authentication function name is unavailable.

### Cookie and CSRF

- Cookies are maintained by `requests.Session`; individual cookie names are not
  asserted by the available Python code or stored evidence.
- The GAS-era workbook says `FUSIONSOLAR_COOKIE` was stored in Script
  Properties and must not be logged or written to cells. Its cookie names and
  renewal rules are not available.
- The CSRF token is read from session JSON as `csrfToken`, must be a string of
  at least 16 characters, and is sent as the `roarand` header.
- API requests also send the application `Referer`,
  `X-Requested-With: XMLHttpRequest`, `X-Timezone-Offset: 540`, and
  `X-Non-Renewal-Session: true`.

Evidence: `FusionSolarClient.__init__`, `is_session_active`, `get_json`,
`post_json`, and `_get_session_data`; workbook tab `02_GAS設定`.

### Re-login and challenges

- HTTP 401/403, redirects, or an HTML response are treated as authentication
  failure. `get_json` and `post_json` call `login` and retry exactly once; a
  second authentication failure is fatal.
- CAPTCHA or verification-code flags/messages are detected and reported as an
  error. No CAPTCHA or confirmation-code solver exists.
- Redirects are followed manually, with a maximum of 12 redirects.

Evidence: `FusionSolarClient.get_json`, `post_json`, `_is_auth_failure`,
`_raise_for_auth_challenge`, and `_follow_redirects`; corresponding tests in
`tests/test_fusionsolar_client.py`.

### Known constraints

- These are FusionSolar Web internal APIs, not a documented public API; the
  workbook warns that compatibility may change without notice.
- The workbook records intermittent HTTP 401 failures even after successful
  automatic login and collection (`02_GAS設定`, `99_取込履歴`).
- Cookie lifetime, CSRF lifetime, request-rate limits, concurrent-session
  behavior, and behavior when CAPTCHA is demanded are not established.

## 2. API inventory

### Status overview

#### Implemented

| API | Endpoint | Method | Parameters | Response status | History/time series | Status | Next verification action |
|---|---|---|---|---|---|---|---|
| `station-kpi-list` | `/rest/pvms/web/report/v1/station/station-kpi-list` | POST | Request body documented below | Stored response confirmed | One day per request; hourly points | live-confirmed | Monitor compatibility and retention |
| `energy-balance` | `/rest/pvms/web/station/v1/overview/energy-balance` | GET | `stationDn`, `timeDim`, `queryTime`, `timeZone`, `timeZoneStr`, `dateStr`, `_` | Stored response and derived Records confirmed | Daily `timeDim=2`; 288 five-minute points | live-confirmed | Confirm units and uncertain key semantics |
| `device-realtime-data` | `/rest/pvms/web/device/v1/device-realtime-data` | GET | `deviceDn`, `_` | Stored responses confirmed for four configured devices | Current snapshot; no history parameter observed | live-confirmed | Verify authoritative device discovery and meter behavior |
| `query-battery-dc` | `/rest/pvms/web/device/v1/query-battery-dc` | GET | `dn`, `sigids`, `moduleId`, `_` | Module 1 has 50 elements; modules 2–4 return successful empty arrays | Current snapshot | live-confirmed | Monitor Signal ID-set and API compatibility |
| Current alarms | `/rest/pvms/fm/v1/query` | POST | JSON body documented below | Stored responses confirmed for four devices | Current state | live-confirmed | Confirm alarm identity and transition semantics |
| Alarm history | `/rest/pvms/fm/v1/query` | POST | JSON body plus `occurUTC` | Stored responses confirmed for four devices | Explicit Unix-millisecond range and pagination | live-confirmed | Confirm retention and stable deduplication identity |

#### Unconfirmed or partially confirmed

| API/capability | Endpoint | Method | Parameters | Response status | History/time series | Status | Next verification action |
|---|---|---|---|---|---|---|---|
| Device inventory / topology / equipment structure | unknown | unknown | `stationDn` relationship unknown | unknown | unknown | candidate | Capture device-list and equipment screens |
| Configuration | unknown | unknown | unknown | unknown | unknown | candidate | Capture configuration screen requests |
| Signal definition/master | unknown | unknown | unknown | Realtime response embeds Signal entries; dedicated API unknown | unknown | candidate | Capture any Signal/master request separately |
| Operation history | unknown | unknown | unknown | unknown | Historical behavior unknown | candidate | Capture operation-history screen requests |
| Maintenance or fault history | unknown | unknown | unknown | unknown | Historical behavior unknown | candidate | Capture maintenance/fault screen requests |
| Monthly energy-balance | Same observed path as `energy-balance` | GET | `timeDim=4` observed; other details as daily request not yet proven | Response not retained as Python RawData | Monthly dimension observed | devtools-observed | Capture complete request and response for a month |
| Yearly energy-balance | Same observed path as `energy-balance` | GET | `timeDim=5` observed; other details as daily request not yet proven | Response not retained as Python RawData | Yearly dimension observed | devtools-observed | Capture complete request and response for a year |

### energy-balance

| Field | Confirmed information |
|---|---|
| API name | `energy-balance` |
| HTTP method | `GET` |
| Endpoint | `/rest/pvms/web/station/v1/overview/energy-balance` |
| Required parameters | `stationDn`, `timeDim=2`, `queryTime`, `timeZone=9`, `timeZoneStr=Asia/Tokyo`, `dateStr`, `_` |
| Date specification | `queryTime` is Unix epoch milliseconds for target-day midnight in Asia/Tokyo; `dateStr` is `YYYY-MM-DD 00:00:00`; `_` is request-time Unix epoch milliseconds. Observed dimensions are `timeDim=2` for day, `4` for month, and `5` for year. Only day collection is implemented. |
| `stationDn` / `deviceDn` / `moduleId` | `stationDn=NE=33812827` is DevTools-observed. No `deviceDn` or `moduleId` evidence. |
| Available information | For `timeDim=2`, `xAxis` contains 288 timestamps at 5-minute intervals from 00:00 through 23:55. Each confirmed 5-minute series array corresponds positionally to `xAxis`. The Python collector preserves the entire response, including `"--"`, without interpreting or converting values. Units and the exact meaning of some keys remain unconfirmed. |
| Evidence state | **live-confirmed**. The Python collector has called the live service and stored the unchanged response as RawData; request behavior is covered by tests. Earlier DevTools and GAS workbook evidence also exists. |
| Past dates | Yes for observed recent dates (2026-07-17 through 2026-07-19). Older range and retention limit are unverified. |
| Recommended collector | `FusionSolarEnergyBalanceCollector` |

Evidence: workbook `01_変更履歴` row for version 0.1.0,
`02_GAS設定` keys `STATION_DN` and `ENERGY_BALANCE_SAMPLE_URL`,
`12_RAW_FusionSolar_5分`, `96_QA_FusionSolar_5分`, and `99_取込履歴` rows
labelled `FusionSolar Web API`. The GAS source/function expected in
`03_EnergyCollector.js` was not available, so its function name remains
unverified. Python request construction is implemented by
`FusionSolarEnergyBalanceCollector.collect_for_date` in
`src/hedp/fusionsolar_energy_balance_collector.py`. Values in
`12_RAW_FusionSolar_5分` are parser output, not proof that identically named
keys occur in the API JSON; `quality=measured_import_derived` also proves that
at least some normalized values may be derived rather than direct keys.

Confirmed top-level response keys are `success`, `data`, and `failCode`.
Confirmed `data` keys are:

- Station/capability metadata: `stationDn`, `stationTimezone`,
  `clientTimezone`, `existInverter`, `existMeter`, `existEnergyStore`,
  `existCharge`, `existIrradiation`, and `existUsePower`.
- Five-minute arrays: `productPower`, `dieselProductPower`, `mainsUsePower`,
  `onGridPower`, `disGridPower`, `usePower`, `selfUsePower`, `chargePower`,
  `dischargePower`, `radiationDosePower`, and `xAxis`.
- Totals and ratios: `totalProductPower`, `totalSelfUsePower`,
  `totalOnGridPower`, `totalBuyPower`, `totalUsePower`, `selfProvide`,
  `onGridPowerRatio`, `selfUsePowerRatioByProduct`, `buyPowerRatio`, and
  `selfUsePowerRatioByUse`.

The response uses `"--"` for some series entries. It is retained as a raw
string, not converted to zero or null. Units and the exact semantics of some
keys are not yet confirmed.

### station-kpi-list

| Field | Confirmed information |
|---|---|
| API name | `station-kpi-list` |
| HTTP method | `POST` |
| Endpoint | `/rest/pvms/web/report/v1/station/station-kpi-list` |
| Required request body used | `currencyUnit`, `counterIDs`, `moList`, `orderBy`, `page`, `pageSize`, `sort`, `statDim`, `statTime`, `statType`, `station`, `timeZone`, `timeZoneStr` |
| Date specification | `statTime`: Unix epoch milliseconds for target-day midnight in Asia/Tokyo |
| `stationDn` / `deviceDn` / `moduleId` | `stationDn` is sent as `moList=[{"moType": 20801, "moString": stationDn}]`. No `deviceDn` or `moduleId`. |
| Available information | Hourly `fmtCollectTimeStr`, `productPower`, `inverterPower`, `onGridPower`, optional `buyPower`, and `powerProfit` |
| Evidence state | **live-confirmed**. |
| Past dates | Yes. The local database contains collected data from 2022-12-15 through 2026-07-20; Python requests one day at a time. |
| Recommended collector | Existing `FusionSolarCollector` (retain); a future rename is not required by this inventory. |

Evidence: `src/hedp/fusionsolar_collector.py` —
`FusionSolarCollector.collect_for_date` and `collect_range`;
`src/hedp/fusionsolar_record_builder.py` —
`FusionSolarRecordBuilder.build`; tests with the same function names in
`tests/test_fusionsolar_collector.py` and
`tests/test_fusionsolar_record_builder.py`; local `hedp.db` contains 1,327
FusionSolar RawData rows with the listed response keys; workbook
`13_RAW_FusionSolar_時間` and `99_取込履歴` contain successful
`station-kpi-list` collection. The corresponding GAS function in
`04_StationCollector.js` is unavailable.

### device-realtime-data

| Field | Confirmed information |
|---|---|
| API name | `device-realtime-data` |
| HTTP method | `GET` |
| Endpoint | `/rest/pvms/web/device/v1/device-realtime-data` |
| Required parameters | `deviceDn`; observed requests also use `_` with a millisecond timestamp, but whether `_` is mandatory is unverified |
| Date specification | None observed; this is a current/realtime response |
| `stationDn` / `deviceDn` / `moduleId` | `deviceDn` is used. No `stationDn` or `moduleId` evidence. |
| Available information | Top-level `buildCode`, `data`, `failCode`, `params`, `success`; within `data`: device `status`, `groupName`, `signals`, `pv2mppt`. Signals expose `id`, `name`, `unit`, display `value`, optional `realValue`, and optional `latestTime`. |
| Evidence state | **live-confirmed** for all four configured candidate device DNs. Python stores one unchanged response per device with the requested `deviceDn` in RawData metadata. |
| Past dates | No historical query is observed. Only the response's latest/current signal timestamp is available. |
| Recommended collector | `FusionSolarDeviceRealtimeCollector` |

Evidence: workbook `24_SPEC_FusionSolar_API` entry for
`device-realtime-data`, `14_RAW_FusionSolar_デバイス` raw responses,
`20_MST_Device`, `21_MST_Signal`, `22_CUR_FusionSolar_蓄電池`,
`23_CUR_FusionSolar_PCS`, and `99_取込履歴`. The expected GAS function in
`02_DeviceCollector.js` is unavailable; its function name is unverified.

Confirmed device signal groups include:

- Battery: operating status, charge/discharge mode, rated capacity, backup
  time, energy charged today, energy discharged today, charge/discharge power,
  bus voltage, and SOC.
- Inverter: status, daily/cumulative energy, active/reactive power, rated
  power, power factor, frequency, current, three grid voltages, startup/shutdown
  time, internal temperature, insulation resistance, output mode, and a Wi-Fi
  signal definition with no observed value.
- Meter candidate: status, active/reactive/apparent power, power factor,
  positive/reverse active and reactive energy, grid voltages, currents, and
  per-line active power names. All observed meter values are `-`, so usable
  meter measurements are not yet proven.

### query-battery-dc

| Field | Confirmed information |
|---|---|
| API name | `query-battery-dc` |
| HTTP method | `GET` |
| Endpoint | `/rest/pvms/web/device/v1/query-battery-dc` |
| Required parameters | `dn`, `sigids`, `moduleId`, `_` |
| Date specification | None observed; current snapshot |
| `stationDn` / `deviceDn` / `moduleId` | `dn=NE=33812831`; module 1 has data, modules 2–4 return `success=true` with `data=[]` |
| Available information | Elements contain `dataType`, `enumMap`, `id`, `latestTime`, `name`, `realValue`, `unit`, and `value` |
| Evidence state | **live-confirmed**; Python has stored unchanged responses for modules 1–4 using the DevTools-confirmed `sigids` |
| Past dates | No historical parameter observed |
| Recommended collector | `FusionSolarBatteryDcCollector` |

Top-level keys are `buildCode`, `data`, `failCode`, `params`, and `success`.
The complete response is stored unchanged. The confirmed `dn` and `sigids`
defaults are defined once in `Configuration`; environment variables are
optional operational overrides.

`quality-battery-dc` checks stored response structure and expected module
coverage; `diagnose-battery-dc` reports per-module counts, empty responses, and
latest acquisition times.

### alarms

| Field | Confirmed information |
|---|---|
| API name | Current alarms and alarm history |
| HTTP method | `POST`, `Content-Type: application/json` |
| Endpoint | `/rest/pvms/fm/v1/query` |
| Common body | `dataType`, `domainType=SOLAR`, `pageNo`, `pageSize`, `nativeMoDn` |
| History body | Common body plus `occurUTC.begin` and `occurUTC.end` Unix milliseconds |
| Device DNs | `NE=33812828`, `NE=33812829`, `NE=33812830`, `NE=33812831` |
| Available information | `offset`, `limit`, `totalCount`, `sizeExceeded`, `groupResult`, `severityStatistics`, `hits` |
| Evidence state | **live-confirmed**; supporting request/response evidence was first observed in DevTools |
| Historical availability | Confirmed explicit range for `dataType=HISTORY`; Python uses Asia/Tokyo date boundaries |
| Recommended collector | `FusionSolarAlarmCollector` |

Top-level keys are `success`, `data`, `failCode`, and `params`. For zero
results, `hits=[]`, `severityStatistics=[]`, `totalCount=0`, `groupResult` is
null or empty, and `offset` is 0 or -1. Python stores every returned page as a
separate unchanged RawData object and continues other devices after one fails.
HISTORY ranges are split into inclusive Asia/Tokyo calendar days; each
device/day/page has metadata for data type, page number/size, target date, and
the exact begin/end milliseconds. Pagination stops using empty/short `hits`,
`totalCount`, `groupResult.totalPage`, or `offset`/`limit`, and aborts on a
repeated response or the maximum page limit.
`quality-alarms` checks stored response structure, success flags, and CURRENT
coverage for configured devices. `diagnose-alarms` reports source/device counts,
latest CURRENT acquisitions, and the total number of stored hits.

## 3. Data inventory

| Data class | API/evidence | Raw data confirmed | Record status |
|---|---|---:|---|
| Generation | `station-kpi-list`: `productPower`, `inverterPower`; `energy-balance`: 5-minute PV; `device-realtime-data`: inverter daily/cumulative energy and active power | Yes | Station KPI and confirmed energy-balance fields are Recordized; realtime Signals are RawData only |
| Consumption | `energy-balance`: 5-minute load; `station-kpi-list`: no separately named consumption key beyond the existing KPI semantics | Yes | Confirmed energy-balance fields are Recordized |
| Grid import | `station-kpi-list`: optional `buyPower`; `energy-balance`: 5-minute import and daily QA total; meter signal names include positive active electricity | Yes for station/energy-balance; meter values not usable in observed response | Confirmed station and energy-balance keys are Recordized; meter Signals are not |
| Grid export | `station-kpi-list`: `onGridPower`; `energy-balance`: 5-minute export and daily QA total; meter signal name includes reverse active energy | Yes for station/energy-balance; meter values not usable in observed response | Confirmed station and energy-balance keys are Recordized; meter Signals are not |
| Battery SOC | `device-realtime-data`, battery signal 10006 | Yes | Unimplemented |
| Battery charge | `energy-balance` 5-minute charge; `device-realtime-data` energy charged today and signed charge/discharge power | Yes | Energy-balance is Recordized; realtime Signals are not |
| Battery discharge | `energy-balance` 5-minute discharge; `device-realtime-data` energy discharged today and signed charge/discharge power | Yes | Energy-balance is Recordized; realtime Signals are not |
| Battery DC information | `query-battery-dc`; `device-realtime-data` also confirms bus voltage | Python RawData and DevTools response confirmed | RawData collector is live-confirmed; no Record conversion |
| Inverter | `device-realtime-data` inverter signal set | Yes | Unimplemented |
| Meter | `device-realtime-data` meter signal definitions | Names yes; measured values no (`-`) | Unimplemented |
| Device status | `device-realtime-data`: top-level status plus battery/inverter status signals | Yes | Unimplemented |
| Alarms | `/rest/pvms/fm/v1/query`, CURRENT and HISTORY | DevTools response confirmed | RawData collector implemented |
| Equipment topology | Four hard-coded candidate DNs and coarse `groupName`/`pv2mppt`; no confirmed discovery/topology API | Partial | Unimplemented |
| 5-minute series | `energy-balance`, 288 points/day observed | Yes; Python preserves the API response as RawData | Confirmed numeric values are Recordized; raw missing markers remain unchanged |
| 1-hour series | `station-kpi-list`, 24-point/day behavior observed; `13_RAW_FusionSolar_時間` | Yes | Five KPI fields are Recordized |
| Daily aggregation | `energy-balance` totals/ratios; inverter daily energy; legacy report files | Yes, but from multiple evidence types | Confirmed energy-balance daily values are separately Recordized |
| Monthly aggregation | `energy-balance` with `timeDim=4` is observed, but a complete response is not retained | No Python RawData | Unimplemented |

The names “generation”, “consumption”, “import”, and “export” for
energy-balance refer to observed normalized columns. Exact raw JSON key names
remain unknown without the legacy request/response parser source.

## 4. Device discovery

### Known device DNs

| Device DN | Observed classification | Confidence/evidence |
|---|---|---|
| `NE=33812828` | Unknown or communication device candidate | No signals; classification unresolved |
| `NE=33812829` | Power meter candidate | Signal names observed, but all values were `-`; provisional |
| `NE=33812830` | Inverter / PCS | Inverter status, energy, and rated-power signals; confirmed in workbook |
| `NE=33812831` | Battery | SOC, charge/discharge, and rated-capacity signals; confirmed in workbook |

The station DN is `NE=33812827`, observed from the DevTools energy-balance
URL (`02_GAS設定`). The four device DNs above are recorded as candidate DNs in
`20_MST_Device` and were all successfully queried through
`device-realtime-data`.

### Discovery status

- The available artifacts do not show automatic device discovery. The source
  of the four candidate DNs is not documented; treat them as previously
  hard-coded/recorded candidates, not a generally valid sequence rule.
- No `mo-details` occurrence or raw response was found.
- `16_FACT_FusionSolar_Signal` has a `moduleId` column but no data rows. This
  proves only that a schema placeholder existed, not a usable module ID or API.
- Unresolved: authoritative discovery endpoint, station-to-device mapping,
  device replacement behavior, meter data availability, meaning of
  `NE=33812828`, and any device/module IDs required by `query-battery-dc`.

## 5. Recommended implementation order

The hourly station path, daily energy-balance path, and five-minute device
snapshot path are implemented. Continue in this order:

1. Monitor live-confirmed Battery DC and alarm RawData quality and compatibility.
2. Observe authoritative device inventory/topology before replacing configured
   candidate DNs.
3. Observe configuration and dedicated Signal/master APIs for the planned
   03:10 collection.
4. Review collected alarms before selecting any derived Record mapping.
5. Confirm complete monthly and yearly energy-balance requests and responses.
6. Add Record conversion only after each new response is durably stored and its
   fields, units, and identifiers are confirmed.

Every step preserves one RawData per API call and avoids inferred fields,
device identifiers, values, units, or signs.

## 6. Unknowns

- The contents and function names of all requested legacy GAS files and
  `FUSIONSOLAR_STATUS.md` are unavailable.
- `energy-balance`: units, exact semantics of some confirmed keys,
  pagination/limits, historical retention, and GAS function name.
- `query-battery-dc` rate limits and whether any history mode exists.
- Whether `_` is required by `device-realtime-data`, its rate limit, unknown-DN
  error shape, and compatibility across FusionSolar updates.
- Charge/discharge power sign convention in `device-realtime-data`.
- Why the meter device returns signal definitions but no values, and whether a
  different endpoint, permission, or operating state is required.
- An authoritative device-discovery endpoint and the meaning of
  `NE=33812828`.
- Any confirmed `mo-details` endpoint, parameters, or response.
- Any usable `moduleId`; the only occurrence is an empty schema column.
- Alarm `hits` element semantics, retention limits, and which observed ID is
  the stable deduplication identity beyond complete response preservation.
- Complete monthly and yearly request/response contracts beyond the observed
  `timeDim=4` and `timeDim=5` values.
- Cookie names/lifetime, CSRF lifetime, request-rate limits, and CAPTCHA
  recovery procedure.
## 7. Collection operations

`device-realtime-data` is live-confirmed in Python. Its complete response, including all Signal values, is retained unchanged every five minutes. Device type assignments remain unconfirmed.

Battery DC joins device realtime and current alarms in the five-minute shared-session job. It also runs in an independent 03:10 Asia/Tokyo job so daily health collection remains observable even when the five-minute job fails or is interrupted. Other equipment, configuration, and Signal-specific APIs remain planned after their method, endpoint, request, and response have been observed.

Current alarms are collected every five minutes as snapshots. History is collected for explicit date ranges and complete pages are preserved. Stable alarm ID semantics remain unconfirmed, so state transitions and derived deduplication are not implemented.

Energy-balance `xAxis` contains 288 five-minute timestamps for a day. The confirmed arrays are paired by index, `"--"` is retained in RawData and omitted only from derived Records, and uncertain units and meanings (including `mainsUsePower`, `disGridPower`, and `radiationDosePower`) remain explicitly unknown.

## 8. DevTools API discovery procedure

Use the browser's Network panel once to inspect these screens in sequence:

1. Home/overview
2. Device list
3. PCS detail
4. Battery detail
5. Battery module detail
6. Meter detail
7. Active alarms
8. Past alarms
9. Equipment information
10. Configuration
11. Month view
12. Year view

For each relevant JSON request, record only:

- Request method and pathname
- Query parameter names, without secret values
- Request body keys, without credentials or tokens
- Response top-level keys and keys directly under `data`
- Whether a time array exists, its length and interval, and the selected period
- Pagination fields
- The role and location of `deviceDn`, `stationDn`, and any module identifier
- The shape of a non-sensitive error response when one occurs naturally

Never record or share Cookie, Authorization, CSRF tokens, session IDs,
passwords, complete request headers, “Copy as cURL” output, or a complete HAR.
Do not deliberately trigger an authentication or equipment error.

The safe sharing format is the Network Request URL reduced to pathname and
query *names*, the Method, a copied response after confirming it contains no
secret, and screenshots that contain no credential or token. Before sharing
JSON, inspect it for user identity, authentication, session, and account data.

## 9. API discovery template

Copy this section within this document for each observed API:

### API name

- Status: `candidate | devtools-observed | implementation-confirmed | live-confirmed`
- Observed date:
- Screen:
- Method:
- Path:
- Query parameter names:
- Request body keys:
- Response top-level keys:
- Response data keys:
- Time-series:
- Interval:
- Historical range:
- Missing-value representation:
- Device/station identifiers:
- Sensitive fields present:
- Notes:
- Implementation decision:
