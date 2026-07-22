#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPOSITORY_ROOT}"
if [[ ! -f .env ]]; then
    echo "Git-ignored .env is required" >&2
    exit 2
fi
set -a
source .env
set +a

LOCK_DIRECTORY="${SUMICORE_DATABASE_LOCK_DIRECTORY:-${HEDP_DATABASE_LOCK_DIRECTORY:-/tmp/com.hedp.database.lock}}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP database job is already running; skipping SwitchBot collection" >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

for log in "${HOME}/Library/Logs/hedp/switchbot.out.log" \
           "${HOME}/Library/Logs/hedp/switchbot.err.log"; do
    if [[ -f "${log}" ]] && [[ "$(stat -f %z "${log}")" -gt 5242880 ]]; then
        mv -f "${log}" "${log}.1"
    fi
done
"${REPOSITORY_ROOT}/.venv/bin/hedp" switchbot collect
