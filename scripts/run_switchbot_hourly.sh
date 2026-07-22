#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCK_DIRECTORY="${HEDP_WRITER_LOCK_DIRECTORY:-/tmp/com.hedp.writer.lock}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP writer is already running; skipping SwitchBot collection" >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
for log in "${HOME}/Library/Logs/hedp/switchbot.out.log" \
           "${HOME}/Library/Logs/hedp/switchbot.err.log"; do
    if [[ -f "${log}" ]] && [[ "$(stat -f %z "${log}")" -gt 5242880 ]]; then
        mv -f "${log}" "${log}.1"
    fi
done
if [[ ! -f .env ]]; then
    echo "Git-ignored .env is required" >&2
    exit 2
fi
set -a
source .env
set +a
"${REPOSITORY_ROOT}/.venv/bin/hedp" switchbot collect
