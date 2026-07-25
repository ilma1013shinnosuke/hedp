#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
source "${SCRIPT_DIR}/operational_metrics.sh"
sumicore_rotate_job_logs equipment
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"
TIMEOUT_RUNNER="${SCRIPT_DIR}/run_with_timeout.py"
EQUIPMENT_TIMEOUT_SECONDS="${SUMICORE_EQUIPMENT_TIMEOUT_SECONDS:-${HEDP_EQUIPMENT_TIMEOUT_SECONDS:-300}}"
SECONDS=0

case "${EQUIPMENT_TIMEOUT_SECONDS}" in
    ''|*[!0-9]*)
        echo "Equipment timeout must be a whole number of seconds" >&2
        sumicore_record_operational_metric equipment failed "${SECONDS}" internal
        exit 2
        ;;
esac
if ((EQUIPMENT_TIMEOUT_SECONDS < 1 || EQUIPMENT_TIMEOUT_SECONDS > 1800)); then
    echo "Equipment timeout must be between 1 and 1800 seconds" >&2
    sumicore_record_operational_metric equipment failed "${SECONDS}" internal
    exit 2
fi

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping equipment collection" >&2
    sumicore_record_operational_metric equipment skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
if "${REPOSITORY_ROOT}/.venv/bin/python" "${TIMEOUT_RUNNER}" \
    "${EQUIPMENT_TIMEOUT_SECONDS}" \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" collect-battery-dc; then
    sumicore_record_operational_metric equipment completed "${SECONDS}" none
    exit 0
else
    exit_code=$?
fi

if [[ "${exit_code}" -eq 124 ]]; then
    sumicore_record_operational_metric equipment timed_out "${SECONDS}" timeout
else
    sumicore_record_operational_metric equipment failed "${SECONDS}" internal
fi
exit "${exit_code}"
