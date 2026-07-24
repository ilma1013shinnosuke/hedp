#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPOSITORY_ROOT}"
if [[ ! -f .env ]]; then
    echo "Git-ignored .env is required" >&2
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
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

"${REPOSITORY_ROOT}/.venv/bin/hedp" switchbot collect
