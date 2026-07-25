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

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping realtime collection" >&2
    sumicore_record_operational_metric device_realtime skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
case "${REALTIME_MODE}" in
    parallel)
        command_name="collect-realtime"
        ;;
    modbus)
        command_name="collect-modbus"
        ;;
    *)
        echo "Invalid realtime collection mode" >&2
        sumicore_record_operational_metric device_realtime failed "${SECONDS}" internal
        exit 2
        ;;
esac
if "${REPOSITORY_ROOT}/.venv/bin/python" \
    "${REPOSITORY_ROOT}/scripts/run_with_timeout.py" 240 \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" "${command_name}"; then
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
