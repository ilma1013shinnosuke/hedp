#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCK_DIRECTORY="/tmp/com.hedp.device-realtime.lock"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "device-realtime collection is already running" >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
status=0
"${REPOSITORY_ROOT}/.venv/bin/hedp" collect-device-realtime || status=1
"${REPOSITORY_ROOT}/.venv/bin/hedp" collect-alarms-current || status=1
exit "${status}"
