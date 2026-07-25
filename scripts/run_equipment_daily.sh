#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
source "${SCRIPT_DIR}/operational_metrics.sh"
sumicore_rotate_job_logs equipment
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"
SECONDS=0

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping equipment collection" >&2
    sumicore_record_operational_metric equipment skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
if "${REPOSITORY_ROOT}/.venv/bin/hedp" collect-battery-dc; then
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
