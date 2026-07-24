#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/log_maintenance.sh"
sumicore_rotate_job_logs device-realtime
LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping realtime collection" >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
"${REPOSITORY_ROOT}/.venv/bin/python" \
    "${REPOSITORY_ROOT}/scripts/run_with_timeout.py" 240 \
    "${REPOSITORY_ROOT}/.venv/bin/hedp" collect-realtime
