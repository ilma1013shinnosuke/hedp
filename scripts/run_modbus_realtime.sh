#!/bin/bash
set -euo pipefail

# Keep the established common database lock.  A future source queue/short
# transaction design may reduce lock contention, but must not weaken the
# current SQLite writer contract during this cutover qualification.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
source "${SCRIPT_DIR}/operational_metrics.sh"
source "${SCRIPT_DIR}/collection_schedule.sh"
sumicore_rotate_job_logs modbus-realtime
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"
TOTAL_TIMEOUT_SECONDS="${SUMICORE_MODBUS_TOTAL_TIMEOUT_SECONDS:-${HEDP_MODBUS_TOTAL_TIMEOUT_SECONDS:-240}}"
ATTEMPT_TIMEOUT_SECONDS="${SUMICORE_MODBUS_ATTEMPT_TIMEOUT_SECONDS:-${HEDP_MODBUS_ATTEMPT_TIMEOUT_SECONDS:-60}}"
MAX_ATTEMPTS="${SUMICORE_MODBUS_MAX_ATTEMPTS:-${HEDP_MODBUS_MAX_ATTEMPTS:-3}}"
RETRY_DELAY_SECONDS="${SUMICORE_MODBUS_RETRY_DELAY_SECONDS:-${HEDP_MODBUS_RETRY_DELAY_SECONDS:-5}}"
SECONDS=0

if ! COLLECTION_INTERVAL_SECONDS="$(sumicore_fusionsolar_collection_interval_seconds)"; then
    sumicore_record_operational_metric modbus_realtime failed "${SECONDS}" configuration
    exit 2
fi

is_whole_number() { [[ "$1" =~ ^[0-9]+$ ]]; }
for value in "${TOTAL_TIMEOUT_SECONDS}" "${ATTEMPT_TIMEOUT_SECONDS}" "${MAX_ATTEMPTS}" "${RETRY_DELAY_SECONDS}"; do
    if ! is_whole_number "${value}"; then
        echo "Modbus timing values must be whole numbers" >&2
        sumicore_record_operational_metric modbus_realtime failed "${SECONDS}" configuration
        exit 2
    fi
done
if ((TOTAL_TIMEOUT_SECONDS < 1 || TOTAL_TIMEOUT_SECONDS > 240 || ATTEMPT_TIMEOUT_SECONDS < 1 || ATTEMPT_TIMEOUT_SECONDS > 60 || MAX_ATTEMPTS < 1 || MAX_ATTEMPTS > 3 || RETRY_DELAY_SECONDS > 30)); then
    echo "Modbus timing values are outside their safe limits" >&2
    sumicore_record_operational_metric modbus_realtime failed "${SECONDS}" configuration
    exit 2
fi
if ((ATTEMPT_TIMEOUT_SECONDS * MAX_ATTEMPTS + RETRY_DELAY_SECONDS * (MAX_ATTEMPTS - 1) > TOTAL_TIMEOUT_SECONDS)); then
    echo "Modbus retry budget exceeds the total timeout" >&2
    sumicore_record_operational_metric modbus_realtime failed "${SECONDS}" configuration
    exit 2
fi

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping Modbus collection" >&2
    sumicore_record_operational_metric modbus_realtime skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}" 2>/dev/null || true' EXIT

cd "${REPOSITORY_ROOT}"
continuity=""
CONTINUITY_ENV=()
if continuity="$("${REPOSITORY_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/modbus_continuity.py" --interval-seconds "${COLLECTION_INTERVAL_SECONDS}" --gap-multiplier 2 2>/dev/null)"; then
    read -r CONTINUITY_ID CONTINUITY_REASON <<< "${continuity}"
    if [[ ! "${CONTINUITY_ID}" =~ ^[0-9a-f]{32}$ ]] || [[ "${CONTINUITY_REASON}" != "initial" && "${CONTINUITY_REASON}" != "continuous" && "${CONTINUITY_REASON}" != "boot_changed" && "${CONTINUITY_REASON}" != "scheduling_gap" && "${CONTINUITY_REASON}" != "boot_evidence_unavailable" && "${CONTINUITY_REASON}" != "boot_evidence_recovered" ]]; then
        CONTINUITY_ID=""
        CONTINUITY_REASON=""
    else
        CONTINUITY_ENV=(
            "SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_ID=${CONTINUITY_ID}"
            "SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_REASON=${CONTINUITY_REASON}"
        )
    fi
else
    CONTINUITY_ID=""
    CONTINUITY_REASON=""
    echo "Modbus continuity evidence is unavailable; collection continues unqualified" >&2
fi

for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if env "${CONTINUITY_ENV[@]}" \
       "${REPOSITORY_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/run_with_timeout.py" \
       "${ATTEMPT_TIMEOUT_SECONDS}" \
       "${REPOSITORY_ROOT}/.venv/bin/hedp" collect-modbus; then
        sumicore_record_operational_metric modbus_realtime completed "${SECONDS}" none
        exit 0
    else
        exit_code=$?
    fi
    # Only exit 75 is emitted for a Modbus transport failure before any
    # response is accepted or persistence begins.  Do not retry timeout,
    # protocol, configuration, or storage failures: their outcome is unknown.
    if [[ "${exit_code}" -ne 75 || "${attempt}" -eq "${MAX_ATTEMPTS}" ]]; then
        break
    fi
    sleep "${RETRY_DELAY_SECONDS}"
done

if [[ "${exit_code}" -eq 124 ]]; then
    sumicore_record_operational_metric modbus_realtime timed_out "${SECONDS}" timeout
else
    sumicore_record_operational_metric modbus_realtime failed "${SECONDS}" internal
fi
exit "${exit_code}"
