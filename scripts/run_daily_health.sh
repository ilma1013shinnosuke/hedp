#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
source "${SCRIPT_DIR}/operational_metrics.sh"
sumicore_rotate_job_logs daily-health
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"
TIMEOUT_RUNNER="${SCRIPT_DIR}/run_with_timeout.py"
DAILY_HEALTH_TIMEOUT_SECONDS="${SUMICORE_DAILY_HEALTH_TIMEOUT_SECONDS:-${HEDP_DAILY_HEALTH_TIMEOUT_SECONDS:-120}}"
SECONDS=0

case "${DAILY_HEALTH_TIMEOUT_SECONDS}" in
    ''|*[!0-9]*)
        echo "Daily health timeout must be a whole number of seconds" >&2
        sumicore_record_operational_metric daily_health failed "${SECONDS}" internal
        exit 2
        ;;
esac
if ((DAILY_HEALTH_TIMEOUT_SECONDS < 1 || DAILY_HEALTH_TIMEOUT_SECONDS > 300)); then
    echo "Daily health timeout must be between 1 and 300 seconds" >&2
    sumicore_record_operational_metric daily_health failed "${SECONDS}" internal
    exit 2
fi

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping health check" >&2
    sumicore_record_operational_metric daily_health skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}" 2>/dev/null || true' EXIT

cd "${REPOSITORY_ROOT}"
if "${REPOSITORY_ROOT}/.venv/bin/python" "${TIMEOUT_RUNNER}" \
    "${DAILY_HEALTH_TIMEOUT_SECONDS}" \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" daily-health --safe-json; then
    sumicore_record_operational_metric daily_health completed "${SECONDS}" none
    exit 0
else
    exit_code=$?
fi

if [[ "${exit_code}" -eq 124 ]]; then
    sumicore_record_operational_metric daily_health timed_out "${SECONDS}" timeout
elif [[ "${exit_code}" -eq 1 ]]; then
    sumicore_record_operational_metric daily_health completed "${SECONDS}" none
else
    sumicore_record_operational_metric daily_health failed "${SECONDS}" internal
fi
exit "${exit_code}"
