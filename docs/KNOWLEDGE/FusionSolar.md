# FusionSolar API knowledge inventory

## Scope and evidence levels

This document records only behavior supported by the current Python code,
stored responses, or the observed GAS-era workbook. It does not carry forward
the GAS architecture.

Evidence labels used below:

- **Python live-confirmed**: the current Python implementation has successfully
  called the API against the live FusionSolar service and stored the returned
  response as RawData.
- **Python implementation-confirmed**: request/parse behavior exists in Python;
  tests use mocked HTTP responses.
- **GAS observed**: successful collection or a raw response is recorded in the
  GAS-era workbook.
- **DevTools observed**: the workbook explicitly says the value came from a
  copied browser request.
- **Unverified**: the available evidence does not establish the behavior.

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

### energy-balance

| Field | Confirmed information |
|---|---|
| API name | `energy-balance` |
| HTTP method | Unverified; the legacy request code/sample URL was not available |
| Endpoint | Full path unverified |
| Required parameters | Exact names unverified. `stationDn` is present in the DevTools-derived sample URL configuration; a target day is used by the observed collector. |
| Date specification | Day-by-day collection is observed; exact URL parameter name and encoding are unavailable. |
| `stationDn` / `deviceDn` / `moduleId` | `stationDn=NE=33812827` is DevTools-observed. No `deviceDn` or `moduleId` evidence. |
| Available information | Observed normalized 5-minute fields: PV, load/consumption, battery charge, battery discharge, grid import, grid export, and self-use energy. Daily API totals for PV, load, import, and export are also recorded in QA. |
| Evidence state | **GAS observed** and **DevTools observed**. Three recent past days have 288 points/day in `96_QA_FusionSolar_5分`; raw rows exist in `12_RAW_FusionSolar_5分`. Not Python-implemented. |
| Past dates | Yes for observed recent dates (2026-07-17 through 2026-07-19). Older range and retention limit are unverified. |
| Recommended collector | `FusionSolarEnergyBalanceCollector` |

Evidence: workbook `01_変更履歴` row for version 0.1.0,
`02_GAS設定` keys `STATION_DN` and `ENERGY_BALANCE_SAMPLE_URL`,
`12_RAW_FusionSolar_5分`, `96_QA_FusionSolar_5分`, and `99_取込履歴` rows
labelled `FusionSolar Web API`. The GAS source/function expected in
`03_EnergyCollector.js` was not available, so method, endpoint, raw response
keys, and function name remain unverified. Values in
`12_RAW_FusionSolar_5分` are parser output, not proof that identically named
keys occur in the API JSON; `quality=measured_import_derived` also proves that
at least some normalized values may be derived rather than direct keys.

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
| Evidence state | **Python live-confirmed**, **Python implementation-confirmed**, and **GAS observed**. |
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
| Evidence state | **GAS observed** for 4/4 candidate device DNs with HTTP 200 and stored raw JSON. Not implemented in Python. |
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
| API name | `query-battery-dc` (requested candidate name only) |
| HTTP method | Unverified |
| Endpoint | Unverified |
| Required parameters | Unverified |
| Date specification | Unverified |
| `stationDn` / `deviceDn` / `moduleId` | All unverified |
| Available information | Unverified; no raw response was found. Do not infer fields from `device-realtime-data`. |
| Evidence state | **Unverified** |
| Past dates | Unverified |
| Recommended collector | `FusionSolarBatteryDcCollector`, only after endpoint, request, identifiers, and raw response are observed |

Evidence search: no occurrence in the repository, Git history, local
filesystem, connected Drive files, workbook API specification, or targeted
public search. The expected legacy source/function was not available.

## 3. Data inventory

| Data class | API/evidence | Raw data confirmed | Record status |
|---|---|---:|---|
| Generation | `station-kpi-list`: `productPower`, `inverterPower`; `energy-balance`: 5-minute PV; `device-realtime-data`: inverter daily/cumulative energy and active power | Yes | Station KPI fields are Recordized; other sources are not implemented in Python |
| Consumption | `energy-balance`: 5-minute load; `station-kpi-list`: no separately named consumption key beyond the existing KPI semantics | Yes in normalized GAS raw | Not implemented for energy-balance |
| Grid import | `station-kpi-list`: optional `buyPower`; `energy-balance`: 5-minute import and daily QA total; meter signal names include positive active electricity | Yes for station/energy-balance; meter values not usable in observed response | `buyPower` Recordized; others unimplemented |
| Grid export | `station-kpi-list`: `onGridPower`; `energy-balance`: 5-minute export and daily QA total; meter signal name includes reverse active energy | Yes for station/energy-balance; meter values not usable in observed response | `onGridPower` Recordized; others unimplemented |
| Battery SOC | `device-realtime-data`, battery signal 10006 | Yes | Unimplemented |
| Battery charge | `energy-balance` 5-minute normalized charge; `device-realtime-data` energy charged today and signed charge/discharge power | Yes | Unimplemented |
| Battery discharge | `energy-balance` 5-minute normalized discharge; `device-realtime-data` energy discharged today and signed charge/discharge power | Yes | Unimplemented |
| Battery DC information | `device-realtime-data` confirms bus voltage; `query-battery-dc` is unverified | Bus voltage only | Unimplemented |
| Inverter | `device-realtime-data` inverter signal set | Yes | Unimplemented |
| Meter | `device-realtime-data` meter signal definitions | Names yes; measured values no (`-`) | Unimplemented |
| Device status | `device-realtime-data`: top-level status plus battery/inverter status signals | Yes | Unimplemented |
| Alarms | No confirmed API or response fields | No | Unimplemented |
| Equipment topology | Four hard-coded candidate DNs and coarse `groupName`/`pv2mppt`; no confirmed discovery/topology API | Partial | Unimplemented |
| 5-minute series | `energy-balance`, 288 points/day observed | Yes in normalized GAS raw | Unimplemented in Python |
| 1-hour series | `station-kpi-list`, 24-point/day behavior observed; `13_RAW_FusionSolar_時間` | Yes | Five KPI fields are Recordized |
| Daily aggregation | `energy-balance` QA totals; inverter daily energy; legacy report files | Yes, but from multiple evidence types | Not separately Recordized by the current Python builder |
| Monthly aggregation | No confirmed Web API request/response | No | Unimplemented |

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

The existing `station-kpi-list` collector and Record builder should remain as
the established hourly path. For new collectors, use this order:

1. **Energy balance RawData** — establish the exact captured request first,
   then save each API response as its own RawData. It is the only observed
   broad 5-minute source for PV, load, import/export, and battery flow. Preserve
   raw values and distinguish direct fields from derived normalized values.
2. **Device realtime RawData** — collect separate RawData per `deviceDn`, first
   for battery `NE=33812831`, inverter `NE=33812830`, then meter candidate
   `NE=33812829`, while retaining the unknown device response. Store every
   observed signal before selecting Records.
3. **Record builders for the two stored RawData families** — only after raw
   responses are durably stored; map confirmed response fields without filling
   missing values or guessing sign conventions.
4. **Battery DC investigation, then RawData collector** — do not implement
   `query-battery-dc` until DevTools establishes its endpoint, method,
   parameters, `deviceDn`/`moduleId`, and a raw response. Once established,
   prioritize it because battery DC is a target domain.
5. **Device discovery investigation** — capture `mo-details` or another
   actually observed discovery request before replacing known candidate DNs.
6. **Alarms and monthly aggregation** — only after an actual request and raw
   response are observed; neither API is currently evidenced.

This order intentionally stores one RawData per API call before Record
conversion and does not infer missing points, fields, device IDs, or signs.

## 6. Unknowns

- The contents and function names of all requested legacy GAS files and
  `FUSIONSOLAR_STATUS.md` are unavailable.
- `energy-balance`: method, full endpoint, exact parameter names, raw response
  keys, pagination/limits, historical retention, and GAS function name.
- `query-battery-dc`: all communication details, identifiers, response fields,
  history support, and evidence state beyond its candidate name.
- Whether `_` is required by `device-realtime-data`, its rate limit, unknown-DN
  error shape, and compatibility across FusionSolar updates.
- Charge/discharge power sign convention in `device-realtime-data`.
- Why the meter device returns signal definitions but no values, and whether a
  different endpoint, permission, or operating state is required.
- An authoritative device-discovery endpoint and the meaning of
  `NE=33812828`.
- Any confirmed `mo-details` endpoint, parameters, or response.
- Any usable `moduleId`; the only occurrence is an empty schema column.
- Alarm API, alarm fields, and historical alarm availability.
- A confirmed monthly-aggregation API.
- Cookie names/lifetime, CSRF lifetime, request-rate limits, and CAPTCHA
  recovery procedure.
