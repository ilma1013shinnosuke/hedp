#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
source "${SCRIPT_DIR}/operational_metrics.sh"
sumicore_rotate_job_logs device-realtime
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"
REALTIME_MODE="${SUMICORE_FUSIONSOLAR_REALTIME_MODE:-${HEDP_FUSIONSOLAR_REALTIME_MODE:-parallel}}"
SECONDS=0

# Keep the established parallel collection behaviour during comparison:
# Modbus and cloud observations share its single bounded job and common
# database lock.  The only addition is anonymous continuity evidence for the
# later read-only qualification.
# The new Modbus-only path is activated only after an explicit installer
# rerun/cutover approval, where it uses the same common lock and a single
# 240-second deadline.
if [[ "${REALTIME_MODE}" == "modbus" ]]; then
    exec "${SCRIPT_DIR}/run_modbus_realtime.sh"
fi

if [[ "${REALTIME_MODE}" != "parallel" ]]; then
    echo "Invalid realtime collection mode" >&2
    sumicore_record_operational_metric device_realtime failed "${SECONDS}" internal
    exit 2
fi

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping realtime collection" >&2
    sumicore_record_operational_metric device_realtime skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}" 2>/dev/null || true' EXIT

cd "${REPOSITORY_ROOT}"
continuity=""
CONTINUITY_ENV=()
if continuity="$("${REPOSITORY_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/modbus_continuity.py" --interval-seconds 300 --gap-multiplier 2 2>/dev/null)"; then
    read -r CONTINUITY_ID CONTINUITY_REASON <<< "${continuity}"
    if [[ "${CONTINUITY_ID}" =~ ^[0-9a-f]{32}$ ]] && [[ "${CONTINUITY_REASON}" == "initial" || "${CONTINUITY_REASON}" == "continuous" || "${CONTINUITY_REASON}" == "boot_changed" || "${CONTINUITY_REASON}" == "scheduling_gap" || "${CONTINUITY_REASON}" == "boot_evidence_unavailable" || "${CONTINUITY_REASON}" == "boot_evidence_recovered" ]]; then
        CONTINUITY_ENV=(
            "SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_ID=${CONTINUITY_ID}"
            "SUMICORE_FUSIONSOLAR_MODBUS_CONTINUITY_REASON=${CONTINUITY_REASON}"
        )
    fi
else
    echo "Modbus continuity evidence is unavailable; collection continues unqualified" >&2
fi

if env "${CONTINUITY_ENV[@]}" \
    "${REPOSITORY_ROOT}/.venv/bin/python" \
    "${REPOSITORY_ROOT}/scripts/run_with_timeout.py" 240 \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" collect-realtime; then
    sumicore_record_operational_metric device_realtime completed "${SECONDS}" none
    exit 0
else
    exit_code=$?
fi

if [[ "${exit_code}" -eq 124 ]]; then
    sumicore_record_operational_metric device_realtime timed_out "${SECONDS}" timeout
else
    sumicore_record_operational_metric device_realtime failed "${SECONDS}" internal
fi
exit "${exit_code}"
