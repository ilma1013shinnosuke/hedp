#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCK_DIRECTORY="${HEDP_WRITER_LOCK_DIRECTORY:-/tmp/com.hedp.writer.lock}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Another HEDP writer is already running; skipping realtime collection" >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}"' EXIT

cd "${REPOSITORY_ROOT}"
"${REPOSITORY_ROOT}/.venv/bin/hedp" collect-realtime
