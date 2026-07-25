#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/operational_metrics.sh"
SECONDS=0
TIMEOUT_RUNNER="${SCRIPT_DIR}/run_with_timeout.py"
SWITCHBOT_TIMEOUT_SECONDS="${SUMICORE_SWITCHBOT_TIMEOUT_SECONDS:-${HEDP_SWITCHBOT_TIMEOUT_SECONDS:-180}}"

case "${SWITCHBOT_TIMEOUT_SECONDS}" in
    ''|*[!0-9]*)
        echo "SwitchBot timeout must be a whole number of seconds" >&2
        sumicore_record_operational_metric switchbot failed "${SECONDS}" internal
        exit 2
        ;;
esac
if ((SWITCHBOT_TIMEOUT_SECONDS < 1 || SWITCHBOT_TIMEOUT_SECONDS > 600)); then
    echo "SwitchBot timeout must be between 1 and 600 seconds" >&2
    sumicore_record_operational_metric switchbot failed "${SECONDS}" internal
    exit 2
fi

cd "${REPOSITORY_ROOT}"
if [[ ! -f .env ]]; then
    echo "Git-ignored .env is required" >&2
    sumicore_record_operational_metric switchbot failed "${SECONDS}" internal
    exit 2
fi
if [[ "${SUMICORE_ENV_LOADED:-}" != "1" ]]; then
    exec "${REPOSITORY_ROOT}/.venv/bin/python" \
        "${REPOSITORY_ROOT}/scripts/run_with_env.py" \
        "${REPOSITORY_ROOT}/.env" -- \
        /usr/bin/env SUMICORE_ENV_LOADED=1 "$0"
fi
source "${SCRIPT_DIR}/log_maintenance.sh"
sumicore_rotate_job_logs switchbot

LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping SwitchBot collection" >&2
    sumicore_record_operational_metric switchbot skipped "${SECONDS}" lock_held
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

if "${REPOSITORY_ROOT}/.venv/bin/python" "${TIMEOUT_RUNNER}" \
    "${SWITCHBOT_TIMEOUT_SECONDS}" \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" switchbot collect; then
    sumicore_record_operational_metric switchbot completed "${SECONDS}" none
    exit 0
else
    exit_code=$?
fi

if [[ "${exit_code}" -eq 124 ]]; then
    sumicore_record_operational_metric switchbot timed_out "${SECONDS}" timeout
else
    sumicore_record_operational_metric switchbot failed "${SECONDS}" internal
fi
exit "${exit_code}"
